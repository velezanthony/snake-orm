"""The helpers BOTH sessions use, in one module that neither of them owns.

They lived in `session.py` with a leading underscore, and `asyncsession.py` imported twelve of them
across the module boundary — three of those from inside functions, dodging a cycle that does not
exist (`rg asyncsession session/session.py` finds nothing). One of the lazy ones ran on every
`AsyncSession()`.

The underscore was API lying about being private: renaming `_pk_condition` would have broken the
other colour, and nothing said so. Here the names carry no underscore, because that is what they
are — the shared half of a seam whose whole doctrine is that the two colours consume the same thing.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from typing import Any, get_origin
from uuid import UUID

from snakeorm.core.exceptions import (
    SnakeRegistryError,
    SnakeUnsupportedFeature,
    SnakeWarning,
)
from snakeorm.dialects import SnakeDialect
from snakeorm.dialects.capabilities import Cap
from snakeorm.drivers import SnakeDriver
from snakeorm.drivers.asyncbase import AsyncDriver
from snakeorm.expressions import SnakeAnd, SnakeCondition, SnakeExpr, SnakeValue
from snakeorm.fields import MISSING
from snakeorm.metadata import SnakeTableInfo
from snakeorm.query import SnakeCompound, SnakeRecursive
from snakeorm.registry import SnakeRegistry, registry, registry_of
from snakeorm.session.coercion import coerce
from snakeorm.session.guards import _guard_declared_limits, _guard_required_values
from snakeorm.times import SnakeUtc


def column_name(column: SnakeExpr[Any]) -> str:
    """SQL name of a column of the bulk SET: it must be DIRECT (one hop). A navigation
    (`User.maker.x`) would point at another table a plain UPDATE cannot reach."""
    if len(column.path) != 1:
        raise SnakeUnsupportedFeature(
            "the SET of a bulk UPDATE uses direct columns of the table, not relationship "
            "navigations."
        )
    return column.path[0]


def guard_set_value(value: object) -> None:
    """Rejects a SET VALUE that navigates a relationship (a path of more than one hop).

    A value like `Truck.maker.nation.id` would point at a joined table, impossible to assign without
    a FROM. A literal or arithmetic over direct columns (`views + 1`) passes through untouched.
    """
    if isinstance(value, SnakeValue) and any(len(path) > 1 for path in value.paths()):
        raise SnakeUnsupportedFeature(
            "the value in the SET of a bulk UPDATE uses columns/arithmetic of the base table, "
            "not relationship navigations (you cannot assign from a joined table without FROM)."
        )


def guard_plain_query(query: object, method: str) -> None:
    """Rejects a COMPOUND or a RECURSIVE where only a plain query fits.

    `count`/`exists`/`select` rewrite the SELECT (they wrap it in `COUNT(*)`/`EXISTS` or change the
    projection), and a set or a CTE do not get rewritten that way: they would have to be wrapped in a
    subquery, which is not emitted yet. The guard lives in ONE place so as not to leave a sibling
    throwing a different error.
    """
    if isinstance(query, (SnakeCompound, SnakeRecursive)):
        raise SnakeUnsupportedFeature(
            f"{method}() does not accept a UNION/EXCEPT/INTERSECT nor a WITH RECURSIVE: they "
            f"would have to be wrapped in a subquery and that is not emitted yet. Fetch the rows "
            f"with session.all(...) and resolve it in Python."
        )


def table_of(instance: object) -> SnakeTableInfo:
    """Resolves an instance's SnakeTableInfo; it fails if its class is not a @snake_model.

    It reinforces the read-only lock at RUNTIME (if it is a VIEW, it rejects the write): the main
    lock is one of TYPES, but this covers whoever switches the checker off or arrives via `Any`.
    """
    table = registry_of(type(instance)).table_of(type(instance))
    if table is None:
        raise SnakeRegistryError(
            f"{type(instance).__name__} is not registered: is it missing @snake_model?"
        )
    if table.is_view:
        raise SnakeUnsupportedFeature(
            f"'{table.name}' is a READ-ONLY view: it does not accept add/update/delete/upsert. "
            f"Creating and editing it live in the migrations (CreateView/AlterView/DropView)."
        )
    return table


def table_with_pk(instance: object) -> SnakeTableInfo:
    """Like `table_of`, but it demands that the table know how to identify ONE row (for
    `refresh`/`update`/`delete`, which work by PK).

    A table with no PK cannot name a row; without this guard the condition came out EMPTY and the
    `WHERE ()` was rejected by Postgres with an opaque error. Inserting is still allowed.
    """
    table = table_of(instance)
    if not table.primary_key.columns:
        raise SnakeUnsupportedFeature(
            f"'{table.name}' has no primary key, so a specific row cannot be identified: "
            f"refresh/update/delete are out. To write into it use add(), and to modify several "
            f"rows at once update_where()/delete_where() with a filter of your own."
        )
    return table


def insert_values(instance: object, table: SnakeTableInfo) -> dict[str, object]:
    """Columns to insert: the ones that have a value (a MISSING, e.g. an autoincrementing PK, is
    OMITTED so the server fills it in). It maps by SQL column name.

    The raw dict is collected BEFORE filtering because the guard needs to see the `MISSING`es:
    omitting one is the normal thing, except on a column nobody else is going to fill in — and that
    is the one that had to be shouted about.
    """
    raw = {
        column.name: getattr(instance, column.attr_name or column.name)
        for column in table.columns
    }
    _guard_required_values(table, raw)
    values = {name: value for name, value in raw.items() if value is not MISSING}
    _guard_declared_limits(table, values)
    return values


_warned_bulk_keys: set[str] = set()
"""Engines already warned that their `add_all` does not give the PKs back. ONCE per process.

A seeding run does dozens of `add_all`s; one warning per batch is noise, and the noise ends up in a
`filterwarnings("ignore")` that also takes down the warnings that did matter.
"""


def warn_bulk_loses_generated_keys(
    dialect: SnakeDialect, table: SnakeTableInfo
) -> None:
    """Warns that on this engine an `add_all` leaves the autoincrementing PKs UNfilled.

    It warns rather than forbids: inserting in bulk without needing the ids is legitimate and is the
    majority case. What cannot happen is that whoever DOES need them fails to find out — because the
    id that never comes back ends up being the foreign key of the next row, and by the time something
    fails, the error is given by the engine over a table that has nothing to do with it.

    `add()` does recover them, with `last_insert_id`. What cannot be done is deducing them for a
    batch: `last_insert_id` speaks of ONE row, and whether the ids of a multi-row INSERT are
    consecutive depends on the server's configuration (`innodb_autoinc_lock_mode`), not on the ORM.
    Guessing there would be writing somebody else's keys in silence, which is worse than not filling
    them in.
    """
    if dialect.supports_returning:
        return
    if not any(column.autoincrement for column in table.primary_key.columns):
        return
    engine = type(dialect).__name__
    if engine in _warned_bulk_keys:
        return
    _warned_bulk_keys.add(engine)
    warnings.warn(
        f"{engine}: add_all() does not fill in the instances' autoincrement id, because this engine "
        f"has no RETURNING and last_insert_id speaks of ONE row only. The rows ARE INSERTED; what is "
        f"left without a value is the `id` in memory. If you need that id afterwards (say, as another "
        f"row's foreign key), use add() per instance. Silence this warning with "
        f"warnings.filterwarnings('ignore', category=SnakeWarning).",
        SnakeWarning,
        stacklevel=3,
    )


def apply_last_insert_id(
    instance: object, table: SnakeTableInfo, driver: SnakeDriver | AsyncDriver
) -> None:
    """Fills the autoincrementing PK in from `last_insert_id`, on engines WITHOUT RETURNING (MySQL).

    The counterpart of `apply_returned`: MySQL only returns the generated id, via `lastrowid`. Only
    a SIMPLE autoincrementing PK and only if it did not arrive set by hand (an explicit PK is not
    clobbered).

    It accepts BOTH drivers because `last_insert_id` does not travel to the database — the cursor of
    the last write stored it — so it is not `async` in either of the two Protocols and this body
    works the same. Having it typed only to the synchronous one is what left the asynchronous session
    never calling it.
    """
    pk_autoinc = [
        column for column in table.primary_key.columns if column.autoincrement
    ]
    if len(pk_autoinc) != 1:
        return
    column = pk_autoinc[0]
    attr = column.attr_name or column.name
    if getattr(instance, attr) is MISSING:
        setattr(instance, attr, driver.last_insert_id)


_warned_caveats: set[tuple[str, Cap]] = set()
"""Caveats already warned about, by (engine, capability). The dedup is carried by the ORM and not by
`warnings` (its "once per process" filter is reset by pytest on every test), so it really is ONCE
whatever happens with the filters.

The key is the CAPABILITY and not the message's text, which is what it used to be: with the textual
key, retouching one comma in a reason made the whole string a different one and everything got
warned about all over again."""


def update_values(instance: object, table: SnakeTableInfo) -> dict[str, object]:
    """Non-PK columns to update: the ones that have a value (a MISSING is OMITTED, it does not write
    the sentinel that used to blow up in `adapt_param`). It validates the `Decimal`s' scale before
    emitting, like the INSERT does. It lives here so the synchronous and asynchronous sessions share
    the SAME path."""
    pk_names = {column.name for column in table.primary_key.columns}
    values = {
        column.name: value
        for column in table.columns
        if column.name not in pk_names
        and (value := getattr(instance, column.attr_name or column.name)) is not MISSING
    }
    _guard_declared_limits(table, values)
    return values


# The Python type that makes each fidelity caveat VISIBLE. It is only warned about if some
# registered model declares that type: telling somebody what happens to a `Decimal` when they have
# none is noise, and the noise ends up in a `filterwarnings("ignore")` for the whole category.
#
# The capabilities that are NOT here are STRUCTURAL and always get warned about: whether the dev is
# going to call `upsert()` or `for_update()` cannot be known by reading the models.
_CAP_PYTHON_TYPE: dict[Cap, object] = {
    Cap.DECIMAL_ORDERING: Decimal,
    Cap.TIMESTAMPTZ: SnakeUtc,
    Cap.INTERVAL: timedelta,
    Cap.JSON: dict,
    Cap.UUID: UUID,
    Cap.BOOLEAN: bool,
    Cap.INT_WIDTHS: int,
    Cap.ARRAYS: list,
    Cap.FLOAT_SPECIALS: float,
}


def declared_python_types(reg: SnakeRegistry) -> set[object]:
    """The Python types the models of THAT registry declare, generics reduced to their base.

    `list[str]` counts as `list`: the caveat belongs to the container (the engine has no arrays), not
    to the type inside it.

    It takes the registry rather than reaching for the global one, because a project built entirely
    on `@snake_model(registry=...)` used to walk an empty list and say NOTHING — and saying nothing
    is precisely what this warning exists to stop.
    """
    used: set[object] = set()
    for model in reg.models():
        # The SAME registry being enumerated, deliberately. This is the one place in the session
        # that ENUMERATES rather than resolves: asking each model for its own registry here would
        # mean walking one registry's list and reading another one's tables, which is a different
        # question from the one the loop is asking.
        table = reg.table_of(model)
        if table is None:
            continue
        for column in table.columns:
            used.add(get_origin(column.python_type) or column.python_type)
    return used


def relevant_caveats(
    dialect: SnakeDialect, reg: SnakeRegistry
) -> tuple[tuple[Cap, str], ...]:
    """The engine's caveats this project is going to notice, with their reason.

    All the structural ones, and the type ones only if there is a model that uses that type — read
    from THAT registry, which is what makes the filtering work for a project that does not use the
    global one.
    """
    declared = declared_python_types(reg)
    return tuple(
        (cap, reason)
        for cap, reason in dialect.capabilities.caveats()
        if cap not in _CAP_PYTHON_TYPE or _CAP_PYTHON_TYPE[cap] in declared
    )


def warn_reduced_fidelity(
    dialect: SnakeDialect, reg: SnakeRegistry | None = None
) -> None:
    """Emits ONE warning per caveat of the engine, each of them ONCE per process (Postgres stays quiet).

    One per capability and not one concatenated: that way the dev can locate the one affecting them,
    and silencing the one they already have under control does not silence the other six.

    `reg` is the registry whose models decide which TYPE caveats are worth mentioning; the global one
    when nobody says otherwise. Without it, a project on a private registry heard nothing at all —
    the quiet end of the same defect the rest of the session had loudly.
    """
    engine = type(dialect).__name__
    for cap, reason in relevant_caveats(dialect, registry if reg is None else reg):
        if (engine, cap) in _warned_caveats:
            continue
        _warned_caveats.add((engine, cap))
        warnings.warn(
            f"{engine}: {reason}. Silence this warning with "
            f"warnings.filterwarnings('ignore', category=SnakeWarning).",
            SnakeWarning,
            stacklevel=3,
        )


def apply_returned(
    instance: object, table: SnakeTableInfo, row: Sequence[object]
) -> None:
    """Assigns to the instance the columns returned by RETURNING (all of them), coercing the type.

    The RETURNING lists the columns in order, so the row matches `table.columns` 1-to-1.

    `column.scale` travels, exactly as `mapper` already passes it on the hydration path. Without it
    this door disagreed with that one over the padding of a `Decimal`, and `refresh()` — whose whole
    job is to fetch the current truth — took an object that `all()` had got right and made it worse.
    """
    for column, value in zip(table.columns, row, strict=True):
        setattr(
            instance,
            column.attr_name or column.name,
            coerce(value, column.python_type, column.scale),
        )


def direct_column(column: SnakeExpr[Any]) -> str:
    """SQL name of a DIRECT column (one hop) used in an upsert's on_conflict/update. A relationship
    navigation would point at another table an INSERT cannot reach."""
    if len(column.path) != 1:
        raise SnakeUnsupportedFeature(
            "the on_conflict/update of an upsert uses direct columns of the table, not "
            "relationship navigations."
        )
    return column.path[0]


def pk_condition(table: SnakeTableInfo, instance: object) -> SnakeCondition:
    """Condition identifying the instance's row by its primary key (simple or composite)."""
    conditions: list[SnakeCondition] = []
    for column in table.primary_key.columns:
        # `getattr` returns `Any` and would contaminate the `==` (the whole tree would go to `Any`);
        # anchoring it to `object` forces `SnakeValue.__eq__(self, other: object) -> SnakeCondition`,
        # with no `Any`.
        value: object = getattr(instance, column.attr_name)
        conditions.append(SnakeExpr(path=(column.name,)) == value)
    if len(conditions) == 1:
        return conditions[0]
    return SnakeAnd(parts=tuple(conditions))
