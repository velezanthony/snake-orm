"""Collection of the column paths a condition of the boolean AST references.

It lives here (not in `query/`) because both `SnakeQuery` and `SnakeCollection` use it, and those two
cannot import each other; `expressions/` imports nobody.
"""

from __future__ import annotations

from snakeorm.expressions.expression import (
    SnakeAnd,
    SnakeComparison,
    SnakeCondition,
    SnakeExists,
    SnakeInList,
    SnakeInSubquery,
    SnakeIsNotNull,
    SnakeIsNull,
    SnakeLike,
    SnakeNot,
    SnakeOr,
    SnakeTupleIn,
    correlation_paths,
)


def condition_paths(condition: SnakeCondition) -> list[tuple[str, ...]]:
    """Column paths referenced by a condition (recursive).

    It delegates to `left.paths()`. The right-hand side of a `SnakeInSubquery` returns `[]`: its
    columns live inside the subquery and must not drag JOINs into the outer query.

    A `SnakeExists` (`.any()`) is the same for its CHILD's columns, and the opposite for the parent
    it correlates against: reached through a to-one (`Contract.owner.memberships`) the parent is a
    table the outer query has to JOIN, and the alias of that JOIN is what the correlation is written
    with. From the root it is still `[]`.
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
    if isinstance(condition, SnakeExists):
        return list(correlation_paths(condition.parent_prefix, condition.pairs))
    return []
