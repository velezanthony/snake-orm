"""Collection of the column paths a condition of the boolean AST references.

It lives here (not in `query/`) because both `SnakeQuery` and `SnakeCollection` use it, and those two
cannot import each other; `expressions/` imports nobody.
"""

from __future__ import annotations

from snakeorm.expressions.expression import (
    SnakeAnd,
    SnakeComparison,
    SnakeCondition,
    SnakeInList,
    SnakeInSubquery,
    SnakeIsNotNull,
    SnakeIsNull,
    SnakeLike,
    SnakeNot,
    SnakeOr,
    SnakeTupleIn,
)


def condition_paths(condition: SnakeCondition) -> list[tuple[str, ...]]:
    """Column paths referenced by a condition (recursive).

    It delegates to `left.paths()`. A `SnakeExists` (`.any()`) and the right-hand side of a
    `SnakeInSubquery` return `[]`: their columns live inside the subquery and must not drag JOINs
    into the outer query.
    """
    if isinstance(condition, SnakeComparison):
        return list(condition.left.paths())
    if isinstance(condition, (SnakeAnd, SnakeOr)):
        return [path for part in condition.parts for path in condition_paths(part)]
    if isinstance(condition, (SnakeInList, SnakeIsNull, SnakeIsNotNull, SnakeLike)):
        return list(condition.left.paths())
    if isinstance(condition, SnakeTupleIn):
        return [path for column in condition.columns for path in column.paths()]
    if isinstance(condition, SnakeInSubquery):
        return list(condition.left.paths())
    if isinstance(condition, SnakeNot):
        return condition_paths(condition.operand)
    return []
