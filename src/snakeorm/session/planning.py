"""What has to be done, WITHOUT doing it: the colourless plan both sessions share.

Here lives the single copy of the decisions — which SQL to emit and how to interpret the rows — and
the synchronous and asynchronous sessions confine themselves to EXECUTING it. Copying the session
(>1000 lines) with an `await` in front would create two places to fix each bug; this branch has
already caught three that way.

The way back (row -> object) lives here too, which used to be in `session.py` with lazy imports: the
extracted core depended on one of its own consumers. No function uses the session, so bringing them
over left the dependency running one way only. Every function returns `(sql, params, apply)`; none
of them touches a driver.
"""

from __future__ import annotations

from snakeorm.decorators.result import snake_result_info
from snakeorm.decorators.row import snake_row_info
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.model import attach_aggregates
from snakeorm.registry import SnakeRegistry, registry_of
from snakeorm.session.coercion import coerce
from snakeorm.sql import emit_insert
from snakeorm.sql import emit_select
from snakeorm.sql.condition import emit_condition

import re
from typing import TYPE_CHECKING, cast

from snakeorm.decorators.result import SnakeResultInfo
from snakeorm.debug.collector import timed_mapping
from snakeorm.fields import SnakePrefetchHop
from snakeorm.fields.relationship import attach_relationship
from snakeorm.metadata import SnakeColumnInfo
from snakeorm.core.exceptions import SnakeUnknownColumn, SnakeValueError
from snakeorm.expressions import (
    SnakeAggFunc,
    SnakeAggregate,
    SnakeAnd,
    SnakeCondition,
    SnakeExpr,
    SnakeTupleIn,
    SnakeValue,
)
from snakeorm.session.mapper import (
    _Dispatch,
    _hydrate_with_plan,
    _Instruction,
    dispatch_for,
    hydrate,
    pk_positions,
    plan_for,
)

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from snakeorm.dialects import SnakeDialect
from snakeorm.metadata import SnakeRelationshipKind, SnakeTableInfo
from snakeorm.sql.refs import qualified

if TYPE_CHECKING:
    # For the checker only. `query/` does not import `session/`, so this would not be a cycle at
    # runtime either; it stays here because nothing in this module CALLS a query, it only describes
    # the shape it receives, and an import paid at start-up for an annotation is an import too many.
    from snakeorm.query import SnakeJoinedQuery, SnakeQuery

T = TypeVar("T")
R = TypeVar("R")

Rows = list[tuple[object, ...]]
"""What a driver returns: raw rows, uninterpreted."""


@dataclass(frozen=True, slots=True)
class Plan(Generic[R]):
    """A parametrised SQL and what to do with whatever comes back.

    `needs_rows` tells EXECUTING apart from QUERYING: whoever built the plan knows it, it is not
    guessed from the string.
    """

    sql: str
    params: tuple[object, ...]
    apply: Callable[[Rows], R]
    needs_rows: bool = True


def plan_insert(
    instance: object,
    table: SnakeTableInfo,
    dialect: SnakeDialect,
    values: dict[str, object],
    apply_returned: Callable[[object, SnakeTableInfo, tuple[object, ...]], None],
) -> Plan[object]:
    """Plan of an INSERT: the SQL and what to do with the row the `RETURNING` gives back.

    With `RETURNING`, ALL the columns come back (server defaults, trigger columns) into the in-memory
    object; without it there is nothing to apply.
    """

    # The discriminator is put in by the CLASS, not by the user: trusting them to remember
    # `Dog(kind="dog")` would store a row that is later read as a generic `Animal` and with no
    # error. It gets overwritten.
    if table.is_polymorphic_child:
        assert table.polymorphic is not None
        values = {**values, table.polymorphic.column: table.polymorphic.value}

    sql, params = emit_insert(table, dialect, values)

    def apply(rows: Rows) -> object:
        """Copies back whatever the server returned."""
        if rows:
            apply_returned(instance, table, rows[0])
        return instance

    return Plan(
        sql=sql, params=params, apply=apply, needs_rows=dialect.supports_returning
    )


def plan_scalar(
    sql: str, params: tuple[object, ...], cast_to: Callable[[object], Any]
) -> Plan[Any]:
    """Plan of a query that returns ONE value (a `COUNT(*)`, an `EXISTS`)."""
    return Plan(sql=sql, params=params, apply=lambda rows: cast_to(rows[0][0]))


@timed_mapping
def project_rows(
    query: SnakeQuery[Any] | SnakeJoinedQuery[Any, Any],
    columns: Sequence[SnakeValue[Any]],
    rows: Rows,
) -> list[tuple[Any, ...]]:
    """Coerces each projected value to the `python_type` that can be determined.

    Colourless: which type each column has does not depend on whether the driver awaited. Both
    sessions use it.

    Timed as mapping too: a `.join()` gives back tuples rather than models, but the work is the same
    work — driver values turned into the Python the user declared — and leaving it out would send it
    to `app_ms`, where the panel says the ORM is not.
    """

    reg = registry_of(query.model)
    root = reg.table_of(query.model)
    types = [_projected_python_type(column, root, reg) for column in columns]
    return [
        tuple(
            coerce(value, declared) if declared is not None else value
            for value, declared in zip(row, types, strict=True)
        )
        for row in rows
    ]


def plan_annotate(
    query: SnakeQuery[Any],
    result: type[Any],
    dialect: SnakeDialect,
    aggregates: dict[str, SnakeValue[Any]],
) -> tuple[str, tuple[object, ...], Callable[[Rows], list[Any]]]:
    """SQL of an `annotate` and how to build the `@snake_result`s with the rows that come back.

    `result` is `type[Any]` and not `type[SnakeResult[Any]]` because it gets CALLED with keywords a
    few lines down: the `__init__` that takes them is synthesised by `@dataclass_transform` on the
    concrete subclass, and the marker base does not carry it. The lock that rejects a class which is
    not a `@snake_result` is the `R: SnakeResult` bound of both sessions, and `snake_result_info`
    behind it — not this annotation.
    """

    info = snake_result_info(result)
    if query.model is not info.base_model:
        raise SnakeEmitError(
            f"The base model of {result.__name__} is {info.base_model.__name__}, but the query is "
            f"over {query.model.__name__}: they do not match. Query the same model that the "
            f"@snake_result declares."
        )
    _validate_aggregate_names(result, info, aggregates)
    base_table = registry_of(info.base_model).table_of(info.base_model)
    assert base_table is not None
    ordered = tuple(aggregates[name] for name, _ in info.scalars)
    sql, params = query.to_annotate_sql(dialect, ordered)
    width = len(base_table.columns)

    @timed_mapping
    def build(rows: Rows) -> list[Any]:
        """Hydrates the base instance and hooks the aggregates onto it."""
        output: list[Any] = []
        for row in rows:
            base: object = _instantiate(info.base_model, base_table, row[:width])
            values = {
                name: coerce(row[width + index], declared)
                for index, (name, declared) in enumerate(info.scalars)
            }
            attach_aggregates(base, values)
            output.append(result(**{info.base_field: base, **values}))
        return output

    return sql, params, build


_ROUTINE_PART = re.compile(r"[^\W\d][\w$]*")
"""One dot-separated part of a routine name: a letter or `_`, then letters, digits, `_` or `$`.

Deliberately the UNQUOTED identifier of the three engines and nothing else. What it leaves out is
the point: a quote, a parenthesis, a semicolon, a space, a newline and a comment marker are all
outside it, so an accepted name cannot end a statement or begin another one.
"""


def routine_name(name: str) -> str:
    """The identifier of a routine, checked and returned as written. The one thing not a parameter.

    Every value in this ORM travels parametrised; this one cannot, because no engine takes a
    placeholder where an identifier goes. `call` and `execute_procedure` are the only doors where
    something from outside reaches the SQL string, so the SHAPE is checked here — the same move
    `SnakeValue.json_get` makes with its key path.

    IT IS NOT QUOTED, and that is measured rather than assumed. On PostgreSQL a routine created with
    a bare `CREATE FUNCTION CalculatePayroll` lands in the catalogue folded to `calculatepayroll`,
    so `SELECT * FROM "CalculatePayroll"()` answers `function CalculatePayroll() does not exist`.
    Quoting here would break every mixed-case routine that works today, and break it at the DRIVER.
    The tables and columns the emitter quotes are the opposite case: those names come from the
    metadata graph, and the ORM is what created them.

    Qualified names are checked PART BY PART (`analytics.monthly_sales`), because the dot is the
    separator and not a character of either name.
    """
    if not all(_ROUTINE_PART.fullmatch(part) for part in name.split(".")):
        raise SnakeValueError(
            f"'{name}' is not a valid routine name. The arguments travel parametrised, but the name "
            f"cannot — no engine takes a placeholder where an identifier goes — so it reaches the "
            f"SQL as written and every dot-separated part has to be a plain identifier: a letter or "
            f"'_', then letters, digits, '_' or '$'. It is not quoted for you either, on purpose: an "
            f"unquoted CREATE FUNCTION CalculatePayroll lands in PostgreSQL's catalogue as "
            f"'calculatepayroll', so quoting the call would stop finding it. For a name that "
            f"genuinely needs quotes, write the statement yourself with raw(...)."
        )
    return name


def plan_call(
    name: str, args: Sequence[object], into: type[Any], dialect: SnakeDialect
) -> tuple[str, tuple[object, ...], Callable[[Rows], list[Any]]]:
    """SQL of a call to a database function (`SELECT * FROM f(...)`) and how to hydrate its rows.

    The ARGS travel parametrised (user data); the NAME is an identifier, so it cannot — it is
    checked by `routine_name` and emitted as written. `into` is `type[Any]` for the same reason
    `plan_annotate`'s `result` is: it gets called with keywords, and the `Row: SnakeRow` bound of
    both sessions is what rejects a class that is not a `@snake_row`.
    """
    checked = routine_name(name)
    placeholders = ", ".join(
        dialect.placeholder(index + 1) for index in range(len(args))
    )
    return (
        f"SELECT * FROM {checked}({placeholders})",
        tuple(args),
        plan_raw(into, source=f"Routine '{checked}'"),
    )


def plan_raw(into: type[Any], source: str = "The query") -> Callable[[Rows], list[Any]]:
    """How to hydrate raw rows into a `@snake_row`, coercing each column to its declared type.

    POSITIONAL mapping, with no shape check against the catalogue: you declare, I hydrate.
    """

    info = snake_row_info(into)

    @timed_mapping
    def hydrate_rows(rows: Rows) -> list[Any]:
        """Builds one `into` per row, checking the width row by row."""
        output: list[Any] = []
        for row in rows:
            if len(row) != len(info.columns):
                raise SnakeEmitError(
                    f"{source} returns {len(row)} column(s) and {into.__name__} declares "
                    f"{len(info.columns)}: the mapping is positional, so they have to match."
                )
            output.append(
                into(
                    **{
                        name: coerce(value, declared)
                        for (name, declared), value in zip(
                            info.columns, row, strict=True
                        )
                    }
                )
            )
        return output

    return hydrate_rows


def plan_to_many_level(
    parents: Sequence[object], hop: SnakePrefetchHop, dialect: SnakeDialect
) -> tuple[str, tuple[object, ...], Callable[[Rows], list[object]]] | None:
    """Plan of ONE to-many level by select-in, or `None` if there is nothing to query.

    `None` when no parent can have children; in that case it has ALREADY assigned the empty list to
    each parent, otherwise the anti-N+1 lock would fire on touching the relationship saying it was
    not loaded.
    """
    from collections import defaultdict

    relationship = hop.relationship
    pairs = relationship.foreign_key.pairs
    child_columns = tuple(child_column for child_column, _ in pairs)
    parent_pk_attrs = tuple(
        _attr_for_column(hop.parent_table, parent_col) for _, parent_col in pairs
    )
    child_fk_attrs = tuple(
        _attr_for_column(hop.child_table, child_col) for child_col in child_columns
    )

    parent_keys = [
        key
        for parent in parents
        if None not in (key := tuple(getattr(parent, attr) for attr in parent_pk_attrs))
    ]
    if not parents or not parent_keys:
        for parent in parents:
            attach_relationship(parent, relationship.name, [])
        return None

    condition = _with_prefetch_filter(
        _select_in_condition(child_columns, parent_keys), hop
    )
    sql, params = emit_select(hop.child_table, dialect, where=condition)

    @timed_mapping
    def attach(rows: Rows) -> list[object]:
        """Groups the children by their FK and assigns the list to each parent (empty if it has none)."""
        children: list[object] = [
            _instantiate(hop.child_model, hop.child_table, row) for row in rows
        ]
        groups: dict[tuple[object, ...], list[object]] = defaultdict(list)
        for child in children:
            groups[tuple(getattr(child, attr) for attr in child_fk_attrs)].append(child)
        for parent in parents:
            key = tuple(getattr(parent, attr) for attr in parent_pk_attrs)
            attach_relationship(parent, relationship.name, groups.get(key, []))
        return children

    return sql, params, attach


def plan_to_one_level(
    parents: Sequence[object], hop: SnakePrefetchHop, dialect: SnakeDialect
) -> tuple[str, tuple[object, ...], Callable[[Rows], list[object]]] | None:
    """Plan of ONE to-one level inside a prefetch, or `None` if there is nothing to query.

    The pairs of a to-one are (parent_local_column, child_referenced_column), so the FK lives in the
    PARENT and the keys of the `IN` are values of its own.
    """

    relationship = hop.relationship
    pairs = relationship.foreign_key.pairs
    parent_fk_attrs = tuple(
        _attr_for_column(hop.parent_table, local_col) for local_col, _ in pairs
    )
    child_ref_columns = tuple(remote_col for _, remote_col in pairs)
    child_ref_attrs = tuple(
        _attr_for_column(hop.child_table, remote_col)
        for remote_col in child_ref_columns
    )

    # ONE key per DISTINCT value, not per parent row: in a to-one the foreign key lives on the
    # parent and it REPEATS. Measured, 50,000 trucks over 50 makers binds 50,000 placeholders and
    # ~150 KB of SQL to ask what 50 placeholders ask; counted over repetitions the batch also
    # crosses SQLite's 32,766-placeholder ceiling, so `parents_per_batch` splits the read into TWO
    # statements where one was enough.
    #
    # `dict.fromkeys` and not a `set`: the order of the parents is the order of the placeholders,
    # and an unordered one would make the emitted SQL differ between runs for no reason.
    #
    # `attach` is unaffected: it indexes the children by key and looks each parent up in that map.
    parent_keys = list(
        dict.fromkeys(
            key
            for parent in parents
            if None
            not in (key := tuple(getattr(parent, attr) for attr in parent_fk_attrs))
        )
    )
    if not parents or not parent_keys:
        for parent in parents:
            attach_relationship(parent, relationship.name, None)
        return None

    condition = _with_prefetch_filter(
        _select_in_condition(child_ref_columns, parent_keys), hop
    )
    sql, params = emit_select(hop.child_table, dialect, where=condition)

    @timed_mapping
    def attach(rows: Rows) -> list[object]:
        """Indexes the children by their referenced key and assigns them to whichever parent is due."""
        children: list[object] = [
            _instantiate(hop.child_model, hop.child_table, row) for row in rows
        ]
        by_key: dict[tuple[object, ...], object] = {
            tuple(getattr(child, attr) for attr in child_ref_attrs): child
            for child in children
        }
        for parent in parents:
            key = tuple(getattr(parent, attr) for attr in parent_fk_attrs)
            attach_relationship(parent, relationship.name, by_key.get(key))
        return list(by_key.values())

    return sql, params, attach


def plan_through_level(
    parents: Sequence[object], hop: SnakePrefetchHop, dialect: SnakeDialect
) -> tuple[str, tuple[object, ...], Callable[[Rows], list[object]]] | None:
    """Plan of a MANY-TO-MANY level: one query with a JOIN against the bridge (one query per level).

    It emits `SELECT target.*, bridge.<parent_fk> FROM target JOIN bridge ... WHERE
    bridge.<parent_fk> IN (...)`. The bridge's extra column travels at the end so it can GROUP by
    parent without a second query (which would be an N+1). `None` — after leaving the empty list on
    each parent — if there are no keys.
    """
    from collections import defaultdict

    relationship = hop.relationship
    bridge = relationship.through
    assert bridge is not None, "plan_through_level only applies to a to_many_through"

    parent_attrs = tuple(
        _attr_for_column(hop.parent_table, parent_col)
        for _, parent_col in bridge.to_parent
    )
    parent_keys = [
        key
        for parent in parents
        if None not in (key := tuple(getattr(parent, attr) for attr in parent_attrs))
    ]
    if not parents or not parent_keys:
        for parent in parents:
            attach_relationship(parent, relationship.name, [])
        return None

    quote = dialect.quote_ident
    target = qualified(hop.child_table.schema, hop.child_table.name, dialect)
    bridge_schema, _, bridge_name = bridge.table.rpartition(".")
    bridge_table = qualified(bridge_schema, bridge_name, dialect)

    columns = ", ".join(f"d.{quote(c.name)}" for c in hop.child_table.columns)
    link = " AND ".join(
        f"p.{quote(bridge_col)} = d.{quote(target_col)}"
        for bridge_col, target_col in bridge.to_target
    )
    bridge_keys = [quote(col) for col, _ in bridge.to_parent]
    filter_cols = ", ".join(f"p.{col}" for col in bridge_keys)

    params: list[object] = []
    sql_groups: list[str] = []
    for key in parent_keys:
        placeholders = ", ".join(
            dialect.placeholder(len(params) + i + 1) for i in range(len(key))
        )
        params.extend(key)
        sql_groups.append(f"({placeholders})" if len(key) > 1 else placeholders)
    items = ", ".join(sql_groups)
    left_side = f"({filter_cols})" if len(bridge_keys) > 1 else filter_cols

    sql = (
        f"SELECT {columns}, {filter_cols} FROM {target} AS d "
        f"JOIN {bridge_table} AS p ON {link} WHERE {left_side} IN ({items})"
    )
    width = len(hop.child_table.columns)

    @timed_mapping
    def attach(rows: Rows) -> list[object]:
        """Groups by the parent key that travels at the end of each row."""
        groups: dict[tuple[object, ...], list[object]] = defaultdict(list)
        children: list[object] = []
        for row in rows:
            child = _instantiate(hop.child_model, hop.child_table, row[:width])
            children.append(child)
            groups[tuple(row[width:])].append(child)
        for parent in parents:
            key = tuple(getattr(parent, attr) for attr in parent_attrs)
            attach_relationship(parent, relationship.name, groups.get(key, []))
        return children

    return sql, tuple(params), attach


def parents_per_batch(hop: SnakePrefetchHop, dialect: SnakeDialect) -> int:
    """How many parents fit in ONE select-in without overshooting the engine's placeholder ceiling.

    The read side used to bind one placeholder per parent and emit a single statement, while
    `add_all` had been slicing by `max_bind_params` since it existed. Past 65,535 parents on Postgres
    (32,766 on SQLite) the driver simply rejected it. There was no decision behind the asymmetry, so
    the fix is the loop that was already there, not a new one.

    Measured in PLACEHOLDERS, not in parents: a composite FK costs one per column, so a two-column
    key halves the batch. And the prefetch filter binds its own out of the same budget, which is why
    they are counted rather than guessed at with a fixed margin — a margin an `in_([...5000 ids])`
    inside the filter walks straight through. Counting them costs one emission per LEVEL (pure string
    building, no database), and levels come in twos and threes.
    """
    # `foreign_key` is a required field of `SnakeRelationshipInfo`, so it is read and not `getattr`'d
    # with a default: the guard that used to be here only looked like caution once the hop was typed.
    per_parent = max(1, len(hop.relationship.foreign_key.pairs))
    spent = 0
    if hop.child_filter is not None:
        _, filter_params = emit_condition(hop.child_filter, dialect)
        spent = len(filter_params)
    return max(1, (dialect.max_bind_params - spent) // per_parent)


def plan_level(
    parents: Sequence[object], hop: SnakePrefetchHop, dialect: SnakeDialect
) -> tuple[str, tuple[object, ...], Callable[[Rows], list[object]]] | None:
    """The plan of whichever level is due, according to the kind of relationship. A single place
    decides which of the three it is, so as not to have two copies of the dispatch table (the second
    one ends up forgetting a row)."""
    if hop.kind is SnakeRelationshipKind.TO_MANY_THROUGH:
        return plan_through_level(parents, hop, dialect)
    if hop.kind is SnakeRelationshipKind.TO_MANY:
        return plan_to_many_level(parents, hop, dialect)
    return plan_to_one_level(parents, hop, dialect)


# -- From row to object: the other half of the plan ---------------------------------------------
# These functions used to live in `session.py` and were asked back for with lazy imports (the
# extracted core depended on its consumer). None of them uses the session: they are ROW logic, and
# this is where they belong.


def _validate_aggregate_names(
    result: type, info: SnakeResultInfo, aggregates: dict[str, SnakeValue[Any]]
) -> None:
    """Checks that the aggregates match the `@snake_result`'s scalar fields EXACTLY, before emitting
    any SQL (a `SnakeEmitError` saying which ones are spare/missing)."""
    expected = {name for name, _ in info.scalars}
    provided = set(aggregates)
    missing = expected - provided
    extra = provided - expected
    if not missing and not extra:
        return
    parts: list[str] = []
    if missing:
        parts.append(f"missing {sorted(missing)}")
    if extra:
        parts.append(f"extra {sorted(extra)}")
    raise SnakeEmitError(
        f"The aggregates do not match the scalar fields of {result.__name__} "
        f"({sorted(expected)}): {'; '.join(parts)}."
    )


def _projected_python_type(
    value: SnakeValue[Any], root: SnakeTableInfo | None, reg: SnakeRegistry
) -> type | None:
    """python_type of a value projected in `select()`, or None if it cannot be determined.

    A column -> the type of its path; an aggregate -> its return type. The rest (arithmetic,
    subqueries) has no declared type: None -> it passes through uncoerced (no type gets invented).
    """
    if root is None:
        return None
    if isinstance(value, SnakeAggregate):
        return _aggregate_python_type(value, root, reg)
    if isinstance(value, SnakeExpr):
        column = _resolve_column(value.path, root, reg)
        return column.python_type if column is not None else None
    return None


def _instantiate(model: type[T], table: SnakeTableInfo, row: Sequence[object]) -> T:
    """Builds an instance of the model with the row's values, in column order.

    It delegates to `mapper.hydrate` (a plan compiled ONCE per table). It is also the ONLY point
    where the concrete class of a polymorphic hierarchy gets decided (the row carries its
    discriminator), and that is why `all`/`first`/`get`/`include` inherit it without noticing. The
    dispatch is two lookups (an already-computed position + a `dict.get`): everything else is fixed
    per table and lives in the plan.
    """
    dispatch = dispatch_for(model, table)
    if dispatch is not None:
        position, by_value = dispatch
        # `isinstance` (not `cast`): the compiler guarantees that the COLUMN is `str`, not that the
        # driver returns one. If it is not, it hydrates as the base, just like an unknown discriminator.
        value = row[position]
        concrete_model = by_value.get(value) if isinstance(value, str) else None
        if concrete_model is not None and concrete_model is not model:
            return cast("T", hydrate(concrete_model, table, row, owner=model))
    return hydrate(model, table, row)


def _instantiate_all(
    model: type[T], table: SnakeTableInfo, rows: Sequence[Sequence[object]]
) -> list[T]:
    """Instantiates ALL the rows resolving dispatch and plan ONCE, not per row.

    For the common case (non-polymorphic) the plan is resolved once and the loop only writes
    attributes. Polymorphism needs to decide the subclass per row, so it falls back to
    `_instantiate`'s path.
    """
    if dispatch_for(model, table) is not None:
        return [_instantiate(model, table, row) for row in rows]
    plan = plan_for(model, table, model)
    return [_hydrate_with_plan(model, plan, row) for row in rows]


@timed_mapping
def instantiate_rows_with_includes(
    segments: Sequence[tuple[tuple[str, ...], type, SnakeTableInfo]],
    rows: Sequence[Sequence[object]],
) -> list[object]:
    """Rebuilds EVERY root of a wide result set (a SELECT with includes), rows already in hand.

    Written once here rather than as the same comprehension in each session: the two sessions are
    twins, and a decision written on one of two twins is a promise that the other will forget it.
    """
    # Every plan is resolved ONCE per segment, before the row loop starts. `_instantiate` and
    # `_pk_is_null` each go through `mapper._entry`, so calling them inside the loop cost three
    # lookups per segment per ROW — 250 of them for 50 rows with one include. The flat path had
    # already solved this (`_instantiate_all` hoists) and `mapper` promises it in writing: "Whoever
    # maps N rows resolves the plan once". The include was the caller that did not keep it.
    #
    # Hoisting stops HERE, at the call. `mapper` invalidates by the table's REFERENCE, so caching
    # these above the call would be a second cache with its own rule — which `_entry`'s docstring
    # forbids, and which would be a worse bug than the one being fixed.
    return [
        _instantiate_with_compiled(compiled, row)
        for compiled in (compile_segments(segments),)
        for row in rows
    ]


def compile_segments(
    segments: Sequence[tuple[tuple[str, ...], type, SnakeTableInfo]],
) -> tuple[_CompiledSegment, ...]:
    """Resolves every segment's plan ONCE. Call it OUTSIDE the row loop; that is the whole point.

    Public within the package because the STREAMING paths need it too: they hydrate row by row from
    a generator, so a helper that compiles internally would resolve per row all over again — which
    is the failure this exists to remove, hidden one layer deeper where a `.all()` test cannot see it.
    """
    return tuple(
        _CompiledSegment(
            prefix=prefix,
            model=model,
            table=table,
            width=len(table.columns),
            dispatch=dispatch_for(model, table),
            plan=plan_for(model, table, model),
            pks=pk_positions(model, table),
        )
        for prefix, model, table in segments
    )


@dataclass(frozen=True, slots=True)
class _CompiledSegment:
    """One segment of a wide row with everything about it already resolved.

    Named `_CompiledSegment` and not `_IncludeSegment`: `query.py` already exports an
    `IncludeSegment`, which is this one's INPUT, and two names one underscore apart for a thing and
    its precompiled form is how a reader ends up debugging the wrong one.
    """

    prefix: tuple[str, ...]
    model: type
    table: SnakeTableInfo
    width: int
    dispatch: _Dispatch
    plan: tuple[_Instruction, ...]
    pks: tuple[int, ...]


def _instantiate_with_compiled(
    segments: Sequence[_CompiledSegment], row: Sequence[object]
) -> object:
    """Rebuilds the root object with its relatives, with every plan already in hand.

    The loop only slices the row and writes: no lookups, no resolution. A relationship with no match
    (a LEFT JOIN with a null PK) is left as None, not as a phantom object.
    """
    objects: dict[tuple[str, ...], object | None] = {}
    offset = 0
    for segment in segments:
        chunk = row[offset : offset + segment.width]
        offset += segment.width
        if segment.prefix and all(chunk[pos] is None for pos in segment.pks):
            objects[segment.prefix] = None
        elif segment.dispatch is not None:
            # A polymorphic segment decides its class per ROW, so it goes the long way round —
            # which is the same exception `_instantiate_all` makes on the flat path.
            objects[segment.prefix] = _instantiate(segment.model, segment.table, chunk)
        else:
            objects[segment.prefix] = _hydrate_with_plan(
                segment.model, segment.plan, chunk
            )
    for segment in segments:
        parent = objects[segment.prefix[:-1]] if segment.prefix else None
        if segment.prefix and parent is not None:
            attach_relationship(parent, segment.prefix[-1], objects[segment.prefix])
    return objects[()]


def _instantiate_with_includes(
    segments: Sequence[tuple[tuple[str, ...], type, SnakeTableInfo]],
    row: Sequence[object],
) -> object:
    """Rebuilds the root object with its relatives from a wide row (a SELECT with includes).

    It slices the row up by segment, instantiates each one and hooks it onto its parent. A
    relationship with no match (a LEFT JOIN with a null PK) is left as None, not as a phantom object.
    """
    objects: dict[tuple[str, ...], object | None] = {}
    offset = 0
    for prefix, model, table in segments:
        width = len(table.columns)
        chunk = row[offset : offset + width]
        offset += width
        objects[prefix] = (
            None
            if prefix and _pk_is_null(model, table, chunk)
            else _instantiate(model, table, chunk)
        )
    for prefix, _model, _table in segments:
        parent = objects[prefix[:-1]] if prefix else None
        if prefix and parent is not None:
            attach_relationship(parent, prefix[-1], objects[prefix])
    return objects[()]


def _select_in_condition(
    child_columns: tuple[str, ...], parent_keys: list[tuple[object, ...]]
) -> SnakeCondition:
    """Filter of the select-in: a simple FK -> `col IN (...)`; a composite FK -> `(a, b) IN ((...),
    ...)` (`SnakeTupleIn`, one row per parent with the tuple of its PK values)."""
    if len(child_columns) == 1:
        column: SnakeExpr[object] = SnakeExpr(path=(child_columns[0],))
        return column.in_([key[0] for key in parent_keys])
    columns: tuple[SnakeValue[object], ...] = tuple(
        SnakeExpr(path=(name,)) for name in child_columns
    )
    return SnakeTupleIn(columns=columns, rows=tuple(parent_keys))


def _attr_for_column(table: SnakeTableInfo, name: str) -> str:
    """Returns a column's Python attribute by its SQL name (to read/group by FK/PK)."""
    for column in table.columns:
        if column.name == name:
            return column.attr_name or column.name
    raise SnakeUnknownColumn(f"Column '{name}' does not exist in '{table.name}'.")


def _aggregate_python_type(
    aggregate: SnakeAggregate[Any], root: SnakeTableInfo, reg: SnakeRegistry
) -> type | None:
    """Return type of an aggregate: COUNT -> int, AVG -> float; SUM/MIN/MAX preserve their column's."""
    if aggregate.func is SnakeAggFunc.COUNT:
        return int
    if aggregate.func is SnakeAggFunc.AVG:
        return float
    if isinstance(aggregate.arg, SnakeExpr):
        column = _resolve_column(aggregate.arg.path, root, reg)
        return column.python_type if column is not None else None
    return None


def _resolve_column(
    path: tuple[str, ...], root: SnakeTableInfo, reg: SnakeRegistry
) -> SnakeColumnInfo | None:
    """Resolves a path (relationships... + column) to its SnakeColumnInfo, or None if unreachable.

    It walks the graph along the path's hops; None on any link that does not match (the caller does
    not coerce).
    """
    table: SnakeTableInfo | None = root
    for step in path[:-1]:
        if table is None:
            return None
        relationship = next(
            (rel for rel in table.relationships if rel.name == step), None
        )
        if relationship is None:
            return None
        # The caller's registry, threaded rather than defaulted. A default of the global one is
        # exactly the shape of the bug: it works until two models share a class name, and then
        # this walk reads a stranger's table and coerces the projection to the wrong type.
        table = reg.resolve_relationship(relationship)[0]
    return table.get_column(path[-1]) if table is not None else None


def _pk_is_null(model: type, table: SnakeTableInfo, chunk: Sequence[object]) -> bool:
    """Tells whether the chunk's PK is all NULL (a LEFT JOIN with no match -> no such relationship).

    The positions come precomputed: resolving them per row was O(columns²) on the `include` path.
    """
    return all(chunk[position] is None for position in pk_positions(model, table))


def _with_prefetch_filter(
    condition: SnakeCondition, hop: SnakePrefetchHop
) -> SnakeCondition:
    """ANDs the hop's filter (if there is one) onto the `WHERE fk IN (...)` of that level's select-in.

    The filter's paths are DIRECT columns of the child (the subquery is over a single table), so they
    are emitted unqualified. It narrows WHICH CHILDREN come back; the grouping afterwards still
    assigns [] to the parents with no matching children.
    """
    if hop.child_filter is None:
        return condition
    return SnakeAnd(parts=(condition, hop.child_filter))
