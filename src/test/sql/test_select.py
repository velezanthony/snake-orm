"""Tests for the SELECT emitter: SnakeTableInfo -> a parameterised (sql, params).

The emitter ORCHESTRATES the shape of the statement (SELECT cols FROM table WHERE) and DELEGATES
whatever is engine-specific (quoting, placeholders) to the dialect. It does not know which engine it
is. Pure, no database.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr, SnakeOrder
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.sql import emit_select


def _name_key() -> SnakeOrder:
    """An ascending sort key on 'username'."""
    return SnakeExpr[str](path=("username",)).asc()


def _age_key_desc() -> SnakeOrder:
    """A descending sort key on 'age'."""
    return SnakeExpr[int](path=("age",)).desc()


def _table(schema: str = "public") -> SnakeTableInfo:
    """The test table 'users', with an id and a username column."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    name_col = SnakeColumnInfo(name="username", python_type=str)
    return SnakeTableInfo(
        name="users",
        columns=(id_col, name_col),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
        schema=schema,
    )


def test_select_all_columns_quoted() -> None:
    """Checks that it emits every column quoted, and no WHERE when there is no condition."""
    sql, params = emit_select(_table(), PostgresDialect())
    assert sql == 'SELECT "id", "username" FROM "public"."users"'
    assert params == ()


def test_select_qualifies_with_schema() -> None:
    """Checks that the table is qualified with its schema (schema.table, both quoted)."""
    sql, _ = emit_select(_table(schema="app"), PostgresDialect())
    assert 'FROM "app"."users"' in sql


def test_select_preserves_column_order() -> None:
    """Checks that the column order in the SELECT follows the order in the metadata."""
    sql, _ = emit_select(_table(), PostgresDialect())
    assert sql.index('"id"') < sql.index('"username"')


def test_select_with_where_appends_condition_and_params() -> None:
    """Checks that with a condition it appends a WHERE with parameterised SQL and its params."""
    where = SnakeExpr[str](path=("username",)) == "Ana"
    sql, params = emit_select(_table(), PostgresDialect(), where=where)
    assert sql == 'SELECT "id", "username" FROM "public"."users" WHERE "username" = %s'
    assert params == ("Ana",)


def test_select_without_where_has_empty_params() -> None:
    """Checks that with no condition the params are an empty tuple (not None)."""
    _, params = emit_select(_table(), PostgresDialect())
    assert params == ()


def test_select_order_by_single_ascending() -> None:
    """Checks that an asc key emits `ORDER BY col ASC`."""
    sql, _ = emit_select(_table(), PostgresDialect(), order_by=(_name_key(),))
    assert sql.endswith('ORDER BY "username" ASC')


def test_select_order_by_multiple_keys_preserve_order() -> None:
    """Checks several sort keys separated by commas, each with its direction."""
    sql, _ = emit_select(
        _table(), PostgresDialect(), order_by=(_name_key(), _age_key_desc())
    )
    assert sql.endswith('ORDER BY "username" ASC, "age" DESC')


def test_select_limit_and_offset_are_parametrized() -> None:
    """Checks that LIMIT/OFFSET go out parameterised and their values land in params."""
    sql, params = emit_select(_table(), PostgresDialect(), limit=10, offset=5)
    assert sql.endswith("LIMIT %s OFFSET %s")
    assert params == (10, 5)


def test_select_where_order_limit_param_ordering() -> None:
    """Checks the overall order (WHERE, ORDER BY, LIMIT) and that the params run WHERE->LIMIT."""
    where = SnakeExpr[int](path=("id",)) > 0
    sql, params = emit_select(
        _table(), PostgresDialect(), where=where, order_by=(_name_key(),), limit=10
    )
    assert sql == (
        'SELECT "id", "username" FROM "public"."users" '
        'WHERE "id" > %s ORDER BY "username" ASC LIMIT %s'
    )
    assert params == (0, 10)
