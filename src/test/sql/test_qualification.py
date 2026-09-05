"""Tests of column qualification with aliases (support for deep JOINs).

Without `qualify` (None) → bare column (`"col"`), single-table backwards compat. With `qualify`
(a prefix→alias callable) → qualified column (`t2."col"`). The qualifier is propagated through the
whole condition, nested AND/OR/NOT included.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.sql import emit_condition
from snakeorm.sql.value import emit_value


def test_value_unqualified_without_qualify() -> None:
    """Checks that with no qualifier the column is emitted bare (as it is today)."""
    result = emit_value(SnakeExpr(path=("username",)), PostgresDialect(), [], None)
    assert result == '"username"'


def test_value_qualifies_root_column_with_alias() -> None:
    """Checks that a root column is qualified with the root alias (empty prefix)."""
    result = emit_value(
        SnakeExpr(path=("username",)), PostgresDialect(), [], lambda _: "t0"
    )
    assert result == 't0."username"'


def test_value_qualifies_deep_column_with_prefix_alias() -> None:
    """Checks that a deep column uses the alias of its relation prefix."""
    aliases = {(): "t0", ("maker",): "t1", ("maker", "nation"): "t2"}
    result = emit_value(
        SnakeExpr(path=("maker", "nation", "name")),
        PostgresDialect(),
        [],
        aliases.__getitem__,
    )
    assert result == 't2."name"'


def test_condition_threads_qualify_to_columns() -> None:
    """Checks that emit_condition threads the qualifier down to the condition's columns."""
    cond = SnakeExpr(path=("maker", "name")) == "SEAT"
    sql, params = emit_condition(cond, PostgresDialect(), qualify=lambda _: "t1")
    assert sql == 't1."name" = %s'
    assert params == ("SEAT",)


def test_condition_qualify_reaches_nested_and_not() -> None:
    """Checks that the qualifier reaches the columns inside nested AND/NOT."""
    cond = (SnakeExpr(path=("a",)) == 1) & ~(SnakeExpr(path=("b",)) == 2)
    sql, _ = emit_condition(cond, PostgresDialect(), qualify=lambda _: "t0")
    assert sql == '(t0."a" = %s AND NOT (t0."b" = %s))'


def test_condition_without_qualify_stays_unqualified() -> None:
    """Checks backwards compat: with no qualifier, emit_condition emits without aliases."""
    sql, _ = emit_condition(SnakeExpr[int](path=("age",)) > 18, PostgresDialect())
    assert sql == '"age" > %s'
