"""Tests of SQL emission for arithmetic: SnakeArith → `(<left> <op> <right>)`, parameterised.

Values ALWAYS travel in `params` (never interpolated into the string). It also covers `emit_update`
with an expression in the SET (`views = views + 1`): exactly what the SnakeValue base enables, and
what makes an atomic increment possible without a read-modify-write.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.sql import emit_update
from snakeorm.sql.value import emit_value


def _table() -> SnakeTableInfo:
    """Table 'posts' with PK 'id' and a counter column 'views'."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name="posts",
        columns=(id_col, SnakeColumnInfo(name="views", python_type=int)),
        primary_key=SnakePrimaryKeyInfo(columns=(id_col,)),
    )


def test_emit_arith_produces_parenthesized_sql() -> None:
    """Checks that a SnakeArith emits `("col" + %s)` with the literal as a placeholder."""
    node = SnakeExpr[int](path=("views",)) + 1
    params: list[object] = []
    sql = emit_value(node, PostgresDialect(), params, None)
    assert sql == '("views" + %s)'
    assert params == [1]


def test_emit_arith_column_operands_consume_no_params() -> None:
    """Checks that column OP column consumes no params: both sides are references."""
    node = SnakeExpr[int](path=("a",)) * SnakeExpr[int](path=("b",))
    params: list[object] = []
    sql = emit_value(node, PostgresDialect(), params, None)
    assert sql == '("a" * "b")'
    assert params == []


def test_emit_arith_nested_keeps_param_order() -> None:
    """Checks param order when nesting: `(views + 1) * 2` → params [1, 2]."""
    node = (SnakeExpr[int](path=("views",)) + 1) * 2
    params: list[object] = []
    sql = emit_value(node, PostgresDialect(), params, None)
    assert sql == '(("views" + %s) * %s)'
    assert params == [1, 2]


def test_emit_arith_never_interpolates_values() -> None:
    """Checks the anti-injection thesis: the value never appears in the string, only in params."""
    node = SnakeExpr[int](path=("views",)) + 999
    params: list[object] = []
    sql = emit_value(node, PostgresDialect(), params, None)
    assert "999" not in sql
    assert params == [999]


def test_emit_update_with_expression_in_set() -> None:
    """Checks `SET "views" = ("views" + %s)` with params (1,): the atomic increment."""
    values = {"views": SnakeExpr[int](path=("views",)) + 1}
    sql, params = emit_update(_table(), PostgresDialect(), values)
    assert sql == 'UPDATE "public"."posts" SET "views" = ("views" + %s)'
    assert params == (1,)


def test_emit_update_still_treats_plain_values_as_literals() -> None:
    """Checks that a plain value in the SET is still a placeholder (nothing changes)."""
    sql, params = emit_update(_table(), PostgresDialect(), {"views": 0})
    assert sql == 'UPDATE "public"."posts" SET "views" = %s'
    assert params == (0,)
