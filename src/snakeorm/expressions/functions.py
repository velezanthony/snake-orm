"""Public aggregate constructors (`count`, `sum_`, `avg`, `min_`, `max_`): a typed API over `SnakeAggregate`.

The TYPE is what adds the value: `select(q, col, count())` types the tuple with no `Any`. Nullability
(straight from SQL): `COUNT` over zero rows is 0 (never NULL) -> `int`; `SUM/AVG/MIN/MAX` over zero
rows is NULL -> `| None` (a type that promises `int` and hands back `None` is worse than no type at
all). The ones that clash with a builtin carry a trailing underscore (`sum_`, `min_`, `max_`).
"""

from __future__ import annotations

from typing import Any, TypeVar

from snakeorm.expressions.expression import (
    SnakeAggFunc,
    SnakeAggregate,
    SnakeOrder,
    SnakeStringAgg,
    SnakeValue,
)

T = TypeVar("T")


def count(
    arg: SnakeValue[Any] | None = None, *, distinct: bool = False
) -> SnakeAggregate[int]:
    """`COUNT(*)` with no argument; `COUNT(col)` or `COUNT(DISTINCT col)` with one. Always `int`."""
    return SnakeAggregate(SnakeAggFunc.COUNT, arg, distinct)


def sum_(arg: SnakeValue[T]) -> SnakeAggregate[T | None]:
    """`SUM(col)`. Preserves the column's type and adds `None`: with no rows to add up, it is NULL."""
    return SnakeAggregate(SnakeAggFunc.SUM, arg)


def avg(arg: SnakeValue[Any]) -> SnakeAggregate[float | None]:
    """`AVG(col)`. The average is a real number (`float`), and it is NULL if there are no rows to average."""
    return SnakeAggregate(SnakeAggFunc.AVG, arg)


def min_(arg: SnakeValue[T]) -> SnakeAggregate[T | None]:
    """`MIN(col)`. Preserves the column's type and adds `None`: with no rows, it is NULL."""
    return SnakeAggregate(SnakeAggFunc.MIN, arg)


def max_(arg: SnakeValue[T]) -> SnakeAggregate[T | None]:
    """`MAX(col)`. Preserves the column's type and adds `None`: with no rows, it is NULL."""
    return SnakeAggregate(SnakeAggFunc.MAX, arg)


def string_agg(
    value: SnakeValue[Any],
    separator: str = ",",
    *,
    order_by: tuple[SnakeOrder, ...] | list[SnakeOrder] = (),
) -> SnakeStringAgg[str | None]:
    """Joins a group's values into one string: `string_agg(Tag.name, ", ", order_by=[...])`.

    `str | None` because an aggregate over no rows is NULL on every engine, exactly like `sum_`.

    THE SEPARATOR DOES NOT TRAVEL THE SAME WAY ON THE THREE, which is why the dialect writes this.
    On PostgreSQL and SQLite it is a normal argument and goes in `params`; on MySQL it is the
    `SEPARATOR` keyword, which was measured to reject a placeholder, so that dialect escapes it
    through the same `literal()` the DDL defaults use.

    `order_by` is worth passing whenever a person reads the result: without it the order is the
    engine's business and can differ between two runs of the same query.
    """
    return SnakeStringAgg[str | None](
        arg=value, separator=separator, order_by=tuple(order_by)
    )
