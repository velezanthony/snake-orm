"""`str` with `max_length`: TEXT is the faithful default, VARCHAR(n) an optional domain restriction.

A Python `str` has no ceiling, so `TEXT` is its 1:1 mapping (just like `BIGINT` for `int`).
`max_length=` does not change the type for performance —in Postgres `VARCHAR(n)` is `TEXT` plus a
length CHECK, same cost— but to IMPOSE a domain limit ("email max 255"). SQLite has no lengths: it
accepts the name and ignores it (a single TEXT affinity), which is documented.

`CHAR(n)` is deliberately not offered: it pads with spaces and the round-trip would change the value.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.dialects import PostgresDialect, SQLiteDialect
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeStrParams,
    SnakeTableInfo,
)
from snakeorm.migration import AlterColumn, diff_schema, emit_create_table

_PG = PostgresDialect()
_LITE = SQLiteDialect()


def _table(email: SnakeColumnInfo) -> SnakeTableInfo:
    """The 'users' table with whatever email column is passed in."""
    pk = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="users",
        columns=(pk, email),
        primary_key=SnakePrimaryKeyInfo(columns=(pk,)),
    )


def test_str_with_max_length_is_varchar_in_postgres() -> None:
    """Verifies that `max_length` emits VARCHAR(n) in Postgres."""
    email = SnakeColumnInfo(
        name="email", python_type=str, type_params=SnakeStrParams(max_length=255)
    )
    assert '"email" VARCHAR(255) NOT NULL' in emit_create_table(_table(email), _PG)


def test_str_without_max_length_stays_text() -> None:
    """Verifies that without `max_length` it stays TEXT: the faithful default is not touched."""
    email = SnakeColumnInfo(name="email", python_type=str)
    assert '"email" TEXT NOT NULL' in emit_create_table(_table(email), _PG)


def test_sqlite_ignores_the_length() -> None:
    """Verifies that SQLite emits TEXT even with `max_length`: it has no lengths, and does not fake them."""
    email = SnakeColumnInfo(
        name="email", python_type=str, type_params=SnakeStrParams(max_length=255)
    )
    assert '"email" TEXT NOT NULL' in emit_create_table(_table(email), _LITE)


def test_changing_the_length_is_a_column_change() -> None:
    """Verifies that the diff sees a length change: going from VARCHAR(100) to VARCHAR(255) migrates."""
    before = _table(
        SnakeColumnInfo(
            name="email", python_type=str, type_params=SnakeStrParams(max_length=100)
        )
    )
    after = _table(
        SnakeColumnInfo(
            name="email", python_type=str, type_params=SnakeStrParams(max_length=255)
        )
    )

    operations = diff_schema([before], [after])
    assert len(operations) == 1
    assert isinstance(operations[0], AlterColumn)


def test_the_same_length_converges() -> None:
    """Verifies that an identical column produces no operations: the autogen has to converge."""
    email = SnakeColumnInfo(
        name="email", python_type=str, type_params=SnakeStrParams(max_length=255)
    )
    assert diff_schema([_table(email)], [_table(email)]) == []


def test_max_length_on_a_non_str_is_rejected() -> None:
    """Verifies that putting `max_length` on a column that is not `str` fails at compile time (fail loud)."""
    with pytest.raises(SnakeModelDefinitionError, match="snake_str"):

        @snake_model(table="ml_bad")
        class Bad(SnakeModel):
            id: SnakeColumn[int] = snake_int(primary_key=True)
            age: SnakeColumn[int] = snake_str(max_length=10)
