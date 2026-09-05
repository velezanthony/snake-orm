"""Tests of the DELETE emitter: (table, where) -> (sql, params).

`DELETE FROM <schema.table> [WHERE <cond>]`. Reuses emit_condition for the WHERE. Pure, no database.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.sql import emit_delete


def _table() -> SnakeTableInfo:
    """Table 'users' with a simple PK on 'id'."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="users",
        columns=(id_col,),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )


def test_delete_with_where() -> None:
    """Checks `DELETE FROM schema.table WHERE ...` with the value in params."""
    where = SnakeExpr[int](path=("id",)) == 1
    sql, params = emit_delete(_table(), PostgresDialect(), where=where)
    assert sql == 'DELETE FROM "public"."users" WHERE "id" = %s'
    assert params == (1,)


def test_delete_without_where_omits_clause() -> None:
    """Checks that with no condition no WHERE is emitted (whole-table DELETE, valid SQL)."""
    sql, params = emit_delete(_table(), PostgresDialect())
    assert sql == 'DELETE FROM "public"."users"'
    assert params == ()


def test_delete_value_is_never_interpolated() -> None:
    """Checks the anti-injection thesis: the value never appears in the string."""
    where = SnakeExpr[str](path=("username",)) == "x'; DROP TABLE users; --"
    sql, params = emit_delete(_table(), PostgresDialect(), where=where)
    assert "DROP TABLE" not in sql
    assert params == ("x'; DROP TABLE users; --",)
