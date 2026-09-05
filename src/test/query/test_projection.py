"""Tests of `.select()` projection: SELECT of specific columns → tuples.

The result is TUPLES (partial data ≠ full model). It compiles the SELECT with the projected
columns, honouring filters and JOINs. Deep filters/columns generate their own JOINs.
"""

from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.query import SnakeQuery


@snake_model(prefix="proj")
class _User:
    """Test model for projection."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    username: SnakeColumn[str] = snake_str()
    age: SnakeColumn[int] = snake_int()


def test_project_single_column() -> None:
    """Checks the SELECT of one specific column."""
    sql, _ = SnakeQuery(_User).to_project_sql(PostgresDialect(), [_User.username])
    assert sql.startswith('SELECT "username" FROM')


def test_project_multiple_columns() -> None:
    """Checks the SELECT of several columns, in order."""
    sql, _ = SnakeQuery(_User).to_project_sql(
        PostgresDialect(), [_User.username, _User.age]
    )
    assert sql.startswith('SELECT "username", "age" FROM')


def test_project_respects_filter() -> None:
    """Checks that the projection keeps the query's WHERE."""
    query = SnakeQuery(_User).filter(_User.age > 18)
    sql, params = query.to_project_sql(PostgresDialect(), [_User.username])
    assert sql.endswith('WHERE "age" > %s')
    assert params == (18,)
