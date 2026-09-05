"""SQL emission of aggregates: `COUNT(*)`, `SUM/AVG/MIN/MAX(col)`, DISTINCT and arithmetic inside.

The argument is emitted with `emit_value`, so it can be a column or a `SnakeArith`. Literal values
(inside an arithmetic node) travel parameterised; the aggregate never interpolates.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeNodeError
from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.expressions.functions import avg, count, max_, min_, sum_
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from snakeorm.sql.value import emit_value
from test.scenarios.deep_domain import Truck


def _emit(node: object) -> tuple[str, list[object]]:
    """Emits a value with Postgres and returns `(sql, params)` for comparison."""
    params: list[object] = []
    sql = emit_value(node, PostgresDialect(), params)
    return sql, params


def test_count_star() -> None:
    """`count()` with no argument emits `COUNT(*)` and consumes no params."""
    sql, params = _emit(count())
    assert sql == "COUNT(*)"
    assert params == []


def test_count_of_column() -> None:
    """`count(col)` emits `COUNT(<col>)`."""
    sql, _ = _emit(count(SnakeExpr(path=("id",))))
    assert sql == 'COUNT("id")'


def test_count_distinct() -> None:
    """`count(col, distinct=True)` emits `COUNT(DISTINCT <col>)`."""
    sql, _ = _emit(count(SnakeExpr(path=("model",)), distinct=True))
    assert sql == 'COUNT(DISTINCT "model")'


def test_sum_avg_min_max() -> None:
    """Each function emits its own name with the argument in parentheses."""
    assert _emit(sum_(SnakeExpr(path=("id",))))[0] == 'SUM("id")'
    assert _emit(avg(SnakeExpr(path=("id",))))[0] == 'AVG("id")'
    assert _emit(min_(SnakeExpr(path=("id",))))[0] == 'MIN("id")'
    assert _emit(max_(SnakeExpr(path=("id",))))[0] == 'MAX("id")'


def test_sum_of_arithmetic_parametrizes_the_literal() -> None:
    """`sum_(col + 1)` emits `SUM((col + %s))` with the literal parameterised (never interpolated)."""
    column: SnakeExpr[int] = SnakeExpr(path=("id",))
    sql, params = _emit(sum_(column + 1))
    assert sql == 'SUM(("id" + %s))'
    assert params == [1]


def test_emit_count_uses_the_aggregate_node() -> None:
    """`emit_count` emits `SELECT COUNT(*)` through the aggregate node, with the exact same SQL as always.

    This is the key cleanup: `COUNT(*)` is no longer a hardcoded literal, it is the very same
    `SnakeAggregate(COUNT)` node that `emit_value` emits. The resulting SQL must be identical.
    """
    snake_link()
    sql, params = SnakeQuery(Truck).to_count_sql(PostgresDialect())
    assert sql == 'SELECT COUNT(*) FROM "public"."trucks"'
    assert params == ()


def test_a_node_with_no_handler_is_refused_by_name() -> None:
    """`emit_value` dispatches by type, and the type it does not know is NAMED back.

    Registering a handler is how a new expression enters the emitter, so forgetting to register one
    is the ordinary way to get here. What has to come out is the class that has no handler; the
    alternative is whatever the emitter's next line does with an object it cannot read, which is a
    `TypeError` about something the caller never wrote.
    """
    with pytest.raises(SnakeNodeError, match="Value expression cannot be emitted: str"):
        _emit("not an expression node")
