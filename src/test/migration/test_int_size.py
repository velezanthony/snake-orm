"""Integer size in the database: Python's `int` is unbounded, the column picks how many bits it books.

A property test uncovered the footgun: `int`→`INTEGER` (int4, ~2,100M) in Postgres but 64 bits in
SQLite, so `followers = 3_000_000_000` works in dev (SQLite) and blows up in prod (Postgres). The
answer is a knob, `SnakeIntSize`, carrying the LITERAL names of the SQL standard
(`SMALLINT`/`INTEGER`/`BIGINT`) so that it reads like SQL, plus a `BIGINT` default —the widest
integer of the engine— which makes both engines agree without anyone having to know the knob.

It is agnostic just like `SnakeServerDefault`: the dialect translates. Postgres emits the literal
type and its SERIAL family; SQLite collapses EVERYTHING to its single `INTEGER` affinity (it draws
no width distinction), which is documented, not hidden.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect, SQLiteDialect
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIntParams,
    SnakeIntSize,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import AlterColumn, diff_schema, emit_create_table

_PG = PostgresDialect()
_LITE = SQLiteDialect()


def test_the_members_are_the_literal_sql_type_names() -> None:
    """Verifies the request: the StrEnum value IS the literal SQL type, not an invented alias."""
    assert SnakeIntSize.SMALLINT == "SMALLINT"
    assert SnakeIntSize.INTEGER == "INTEGER"
    assert SnakeIntSize.BIGINT == "BIGINT"


def test_postgres_maps_each_size_to_its_literal_type() -> None:
    """Verifies that Postgres emits the exact SQL type of each size."""
    assert (
        _PG.map_type(int, params=SnakeIntParams(size=SnakeIntSize.SMALLINT))
        == "SMALLINT"
    )
    assert (
        _PG.map_type(int, params=SnakeIntParams(size=SnakeIntSize.INTEGER)) == "INTEGER"
    )
    assert (
        _PG.map_type(int, params=SnakeIntParams(size=SnakeIntSize.BIGINT)) == "BIGINT"
    )


def test_postgres_default_is_the_widest_integer() -> None:
    """Verifies that an `int` with no knob is BIGINT: the widest, to kill the footgun by default."""
    assert _PG.map_type(int) == "BIGINT"


def test_postgres_autoincrement_uses_the_matching_serial() -> None:
    """Verifies that the autoincrement uses the SERIAL family of the size: a BIGINT PK is BIGSERIAL."""
    assert (
        _PG.map_type(
            int, autoincrement=True, params=SnakeIntParams(size=SnakeIntSize.SMALLINT)
        )
        == "SMALLSERIAL"
    )
    assert (
        _PG.map_type(
            int, autoincrement=True, params=SnakeIntParams(size=SnakeIntSize.INTEGER)
        )
        == "SERIAL"
    )
    assert (
        _PG.map_type(
            int, autoincrement=True, params=SnakeIntParams(size=SnakeIntSize.BIGINT)
        )
        == "BIGSERIAL"
    )
    assert (
        _PG.map_type(int, autoincrement=True) == "BIGSERIAL"
    )  # the default is wide as well


def test_sqlite_collapses_every_size_to_integer() -> None:
    """Verifies that SQLite ignores the width: its ONLY integer affinity is INTEGER (always 64 bits).

    It is not a bug: SQLite has no SMALLINT/BIGINT as distinct types. The name is accepted so that
    the model stays portable, but the width is not honoured, and that is documented.
    """
    assert (
        _LITE.map_type(int, params=SnakeIntParams(size=SnakeIntSize.SMALLINT))
        == "INTEGER"
    )
    assert (
        _LITE.map_type(int, params=SnakeIntParams(size=SnakeIntSize.INTEGER))
        == "INTEGER"
    )
    assert (
        _LITE.map_type(int, params=SnakeIntParams(size=SnakeIntSize.BIGINT))
        == "INTEGER"
    )
    assert _LITE.map_type(int) == "INTEGER"


def _table(size: SnakeIntSize) -> SnakeTableInfo:
    """The 'metrics' table with a `count` column of whatever integer size is passed in."""
    pk = SnakeColumnInfo(name="id", python_type=int)
    count = SnakeColumnInfo(
        name="count", python_type=int, type_params=SnakeIntParams(size=size)
    )
    return SnakeTableInfo(
        name="metrics",
        columns=(pk, count),
        primary_key=SnakePrimaryKeyInfo(columns=(pk,)),
    )


def test_the_size_reaches_the_ddl() -> None:
    """Verifies that the chosen size reaches the Postgres CREATE TABLE as it stands."""
    ddl = emit_create_table(_table(SnakeIntSize.SMALLINT), _PG)
    assert '"count" SMALLINT NOT NULL' in ddl


def test_changing_the_size_is_a_column_change() -> None:
    """Verifies that the diff sees it: going from INTEGER to BIGINT is a real column change.

    Without this, widening the range of an already migrated column would generate no migration and
    it would fall short in production without anyone finding out —the same hole NUMERIC precision
    had—.
    """
    before = _table(SnakeIntSize.INTEGER)
    after = _table(SnakeIntSize.BIGINT)

    operations = diff_schema([before], [after])
    assert len(operations) == 1
    assert isinstance(operations[0], AlterColumn)


def test_the_same_size_converges() -> None:
    """Verifies that an identical column produces no operations: the autogen has to converge."""
    assert (
        diff_schema([_table(SnakeIntSize.BIGINT)], [_table(SnakeIntSize.BIGINT)]) == []
    )
