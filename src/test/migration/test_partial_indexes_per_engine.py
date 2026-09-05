"""A partial index is not something all three engines have, and the ORM has to SAY so.

WHAT WAS BROKEN, MEASURED. `emit_create_index` wrote the `WHERE` of a partial index to the three
engines alike. Postgres and SQLite both have partial indexes; MySQL/MariaDB do NOT — the clause is
not in their `CREATE INDEX` grammar at all — so the statement the ORM handed the server was::

    CREATE INDEX `ix_warehouses_active_code` ON `warehouses` (`code`) WHERE `active` = 1
    ERROR 1064 (42000): ... check the manual ... near 'WHERE `active` = 1'

Verified against MariaDB 11.8. That is the ORM emitting SQL the server rejects, which is the one
outcome the doctrine forbids: neither stopping nor degrading, just failing late and badly, with a
message that names neither the index, nor the model, nor what to do instead.

THE TWO HALVES ARE DIFFERENT DECISIONS, and that is why one capability produces two behaviours:

- A SEARCH partial index is an OPTIMISATION. Emitting it over the whole table finds the same rows
  and stores the same bytes; what it costs is space and a little write time. That is a degradation
  of exactly the kind this catalogue exists to declare, and the session announces it once.
- A UNIQUE partial index is INTEGRITY. Widening `UNIQUE(email) WHERE deleted_at IS NULL` into
  `UNIQUE(email)` forbids rows the domain allows — re-registering a soft-deleted address stops
  working — and dropping the uniqueness instead leaves the database without a rule the model
  declares. No warning repairs either, so the plan refuses.

`Cap` does not distinguish the two, and it should not: `Cap` describes the ENGINE, and the engine has
exactly one gap. What tells them apart is the index's own `unique`, which the metadata already
carries and `SnakeIndexInfo.is_constraint` already reads.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.dialects.base import SnakeDialect
from snakeorm.dialects.capabilities import Cap, Full, Nope
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import CreateIndex, CreateTable, emit_create_index, realize

_ID = SnakeColumnInfo(name="id", python_type=int)
_CODE = SnakeColumnInfo(name="code", python_type=str)
_ACTIVE = SnakeColumnInfo(name="active", python_type=bool)
# The demo's own condition (`frameworks/shared/models/inventory_models.py`), because the engine's
# refusal was found there and not in a laboratory table.
_ONLY_ACTIVE = SnakeExpr[bool](path=("active",)) == True  # noqa: E712 - a SQL condition

_SEARCH = SnakeIndexInfo(
    columns=("code",), name="ix_warehouses_active_code", where=_ONLY_ACTIVE
)
_UNIQUE = SnakeIndexInfo(
    columns=("code",),
    unique=True,
    name="uq_warehouses_active_code",
    where=_ONLY_ACTIVE,
)
_PLAIN = SnakeIndexInfo(columns=("code",), name="ix_warehouses_code")


def _table(*indexes: SnakeIndexInfo) -> SnakeTableInfo:
    """The 'warehouses' table of the demo domain, with the indexes under test."""
    return SnakeTableInfo(
        name="warehouses",
        columns=(_ID, _CODE, _ACTIVE),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        indexes=indexes,
    )


_HAS_PARTIAL: tuple[tuple[str, SnakeDialect], ...] = (
    ("PostgresDialect", PostgresDialect()),
    ("SQLiteDialect", SQLiteDialect()),
)


@pytest.mark.parametrize(
    "engine,dialect",
    (*_HAS_PARTIAL, ("MySQLDialect", MySQLDialect())),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_every_dialect_answers_about_partial_indexes(
    engine: str, dialect: SnakeDialect
) -> None:
    """The three engines ANSWER the new capability, and answer what they really do.

    The catalogue already refuses to build a dialect that skips a member, so the value here is not
    that they answered but WHAT they answered: a wrong `Full()` would put the invalid SQL straight
    back, with the catalogue vouching for it.
    """
    support = dialect.capabilities.support_for(Cap.PARTIAL_INDEXES)

    if engine == "MySQLDialect":
        assert isinstance(support, Nope), support
        assert support.reason.strip(), support
    else:
        assert isinstance(support, Full), support


@pytest.mark.parametrize(
    "engine,dialect", _HAS_PARTIAL, ids=[n for n, _ in _HAS_PARTIAL]
)
def test_the_engines_that_have_partial_indexes_still_get_the_where(
    engine: str, dialect: SnakeDialect
) -> None:
    """The fix does not cost the two engines that DO have partial indexes anything.

    It is the control half: a guard written as "drop the WHERE" with no capability behind it would
    pass every MySQL assertion in this file and quietly turn Postgres's soft-delete index into a
    full one.
    """
    assert " WHERE " in emit_create_index(_table(), _SEARCH, dialect)
    assert " WHERE " in emit_create_index(_table(), _UNIQUE, dialect)


def test_mysql_gets_a_full_index_instead_of_invalid_sql() -> None:
    """On MySQL the search index loses its `WHERE` and becomes a whole-table index.

    Not a silent swap: `Cap.PARTIAL_INDEXES` is structural, so the session announces the reason once
    per process the moment it opens against this engine.
    """
    emitted = emit_create_index(_table(), _SEARCH, MySQLDialect())

    assert emitted == (
        "CREATE INDEX `ix_warehouses_active_code` ON `warehouses` (`code`)"
    )
    assert "WHERE" not in emitted


def test_mysql_keeps_emitting_a_plain_index_untouched() -> None:
    """An index with no `where=` is not a partial one and nothing about it changes."""
    assert emit_create_index(_table(), _PLAIN, MySQLDialect()) == (
        "CREATE INDEX `ix_warehouses_code` ON `warehouses` (`code`)"
    )


def test_a_search_partial_index_is_planned_on_mysql() -> None:
    """The plan LETS THROUGH what can be degraded honestly, on both operations that create one.

    An index is an optimisation, and refusing to migrate over one would make a single line of a
    model un-portable — the same reasoning by which `emit_comments` translates to nothing on the two
    engines that store no comments instead of stopping the migration.
    """
    dialect = MySQLDialect()
    table = _table(_SEARCH)

    assert realize([CreateIndex(table, _SEARCH)], dialect) == [
        CreateIndex(table, _SEARCH)
    ]
    assert realize([CreateTable(table)], dialect) == [CreateTable(table)]


@pytest.mark.parametrize(
    "operation",
    (CreateIndex(_table(_UNIQUE), _UNIQUE), CreateTable(_table(_UNIQUE))),
    ids=("CreateIndex", "CreateTable"),
)
def test_a_unique_partial_index_stops_the_plan_on_mysql(
    operation: CreateIndex | CreateTable,
) -> None:
    """A partial UNIQUE stops in the PLAN, naming the index and the table.

    BOTH operations, and `CreateTable` is the one that matters: it emits the whole table's indexes
    inline, and it is the path a first migration —and the demos' bootstrap— take. A guard that only
    knew about `CreateIndex` would report itself green while letting the real path through.
    """
    with pytest.raises(SnakeMigrationError) as error:
        realize([operation], MySQLDialect())

    message = str(error.value)
    assert "uq_warehouses_active_code" in message
    assert "warehouses" in message
    assert "partial" in message.lower()


@pytest.mark.parametrize(
    "engine,dialect", _HAS_PARTIAL, ids=[n for n, _ in _HAS_PARTIAL]
)
def test_a_unique_partial_index_is_planned_where_the_engine_has_them(
    engine: str, dialect: SnakeDialect
) -> None:
    """The control for the refusal: on the two engines that have partial indexes, nothing stops.

    Without this, a guard that raised for every engine would satisfy the test above and break the
    feature everywhere else.
    """
    table = _table(_UNIQUE)

    assert realize([CreateIndex(table, _UNIQUE)], dialect) == [
        CreateIndex(table, _UNIQUE)
    ]
    assert realize([CreateTable(table)], dialect) == [CreateTable(table)]


def test_the_guard_sees_every_operation_that_creates_an_index() -> None:
    """Whatever emits a `CREATE INDEX` is READ by the guard, found in the source and not listed here.

    This is the half that makes the rest worth running. The guard is CONDITIONAL —it depends on the
    index carried, not on the operation's type— so it cannot live in `_REQUIREMENTS`, and therefore
    `test_every_operation_declares_its_capability` cannot see it. Something has to, or a fifth
    operation that creates an index arrives and slips past in silence, which is exactly how
    `CreateTable` nearly did.
    """
    import inspect

    from snakeorm.migration import operations as operations_module
    from snakeorm.migration.realize import _INDEX_CREATORS

    # The source of `up_sql` and not of the whole class: `DropIndex.down_sql` also calls
    # `emit_create_index` (undoing a drop recreates the index), and reading the class whole would
    # demand a guard over an operation that only ever emits a `DROP` in the direction it is applied.
    emitting = {
        name
        for name, value in inspect.getmembers(operations_module, inspect.isclass)
        if value.__module__ == operations_module.__name__
        and any(
            member == "up_sql" and "emit_create_index" in inspect.getsource(function)
            for member, function in inspect.getmembers(value, inspect.isfunction)
        )
    }

    assert emitting, "no operation emits a CREATE INDEX any more: this scan went blind"
    assert emitting == {creator.__name__ for creator in _INDEX_CREATORS}, (
        f"operations that emit a CREATE INDEX and the partial-index guard does not read: "
        f"{sorted(emitting - {creator.__name__ for creator in _INDEX_CREATORS})}. Add it to "
        f"`_INDEX_CREATORS` and teach `_created_indexes` where its indexes live."
    )
