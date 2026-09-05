"""Window functions: `<func> OVER (PARTITION BY ... ORDER BY ...)`.

They compute one value per row by looking at NEIGHBOURING rows without collapsing them (unlike a
GROUP BY). Without windows, that gets solved with a correlated subquery per row (the N+1 of SQL).
`SnakeWindow` is a plain `SnakeValue` (it gets projected and dispatched by type). It is not allowed
in WHERE/GROUP BY/HAVING (SQL evaluates them afterwards): the condition emitter watches for that.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, TypeVar

from snakeorm.core.exceptions import SnakeUnsupportedFeature, SnakeValueError

from snakeorm.expressions.expression import (
    SnakeAggregate,
    SnakeArith,
    SnakeOrder,
    SnakeValue,
)

T = TypeVar("T")


# `eq=False` is NOT optional: `SnakeValue.__eq__` returns `SnakeCondition`, and a dataclass `__eq__`
# would return `bool`, breaking `window == value`. Same reason in `SnakeAggregate` and `SnakeOrder`.
@dataclass(frozen=True, slots=True, eq=False)
class SnakeWindow(SnakeValue[T]):
    """`<func>(<arg>...) OVER (PARTITION BY ... ORDER BY ...)`.

    `func` is the SQL NAME, kept as a string because two families live side by side (ranking, and
    aggregates used as windows, which already have their own enum): a union enum would lie.
    `extra_args` are literals of the function (the offset of `LAG`/`LEAD`), parametrised like every
    other value.
    """

    func: str
    arg: SnakeValue[Any] | None = None
    extra_args: tuple[object, ...] = ()
    partition_by: tuple[SnakeValue[Any], ...] = ()
    order_by: tuple[SnakeOrder, ...] = ()
    frame: SnakeFrame | None = None

    def over(
        self,
        *,
        partition_by: tuple[SnakeValue[Any], ...] | list[SnakeValue[Any]] = (),
        order_by: tuple[SnakeOrder, ...] | list[SnakeOrder] = (),
        frame: SnakeFrame | None = None,
    ) -> SnakeWindow[T]:
        """The same function with its window defined. Without `over(...)`, the window is ALL the rows.

        `frame` is what turns a running total into a MOVING one. Without it the default frame runs
        from the start of the partition to the current row, which is one useful answer out of many:
        a trailing average, a centred window or a look-ahead all need the frame said out loud.

        A FRAME WITHOUT AN ORDER IS REFUSED. `6 PRECEDING` has to be preceding IN something, and with
        no `ORDER BY` the engine picks an order of its own — so the same query answers differently on
        two runs with nothing to show for it. That is the shape of failure this ORM does not ship.

        It returns a NEW node (immutable AST): reusing a stored window holds no surprises.
        """
        if frame is not None and not order_by:
            raise SnakeUnsupportedFeature(
                "A window frame needs an order to be measured against: pass order_by= alongside "
                "frame=. Without it, '6 PRECEDING' is six rows before whichever row the engine "
                "happened to put first, which can change between two runs of the same query."
            )
        return replace(
            self,
            partition_by=tuple(partition_by),
            order_by=tuple(order_by),
            frame=frame,
        )

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """Paths of everything the window touches (argument, partition, order): all three plan JOINs."""
        paths: list[tuple[str, ...]] = []
        if self.arg is not None:
            paths.extend(self.arg.paths())
        for value in self.partition_by:
            paths.extend(value.paths())
        for key in self.order_by:
            paths.extend(key.expr.paths())
        return tuple(paths)


def _rank_window(name: str) -> SnakeWindow[int]:
    """Ranking function with no argument: it returns one integer per row."""
    return SnakeWindow[int](func=name)


def row_number() -> SnakeWindow[int]:
    """`ROW_NUMBER()`: position within the partition, with no ties (1, 2, 3, 4...)."""
    return _rank_window("ROW_NUMBER")


def rank() -> SnakeWindow[int]:
    """`RANK()`: position with ties, SKIPPING the gaps (1, 2, 2, 4...)."""
    return _rank_window("RANK")


def dense_rank() -> SnakeWindow[int]:
    """`DENSE_RANK()`: position with ties and NO gaps (1, 2, 2, 3...)."""
    return _rank_window("DENSE_RANK")


def lag(value: SnakeValue[T], offset: int = 1) -> SnakeWindow[T | None]:
    """`LAG(value, n)`: the value of the row n positions BEFORE in the window.

    Optional: on the first n rows there is no previous one and the result is NULL.
    """
    return SnakeWindow[T | None](func="LAG", arg=value, extra_args=(offset,))


def lead(value: SnakeValue[T], offset: int = 1) -> SnakeWindow[T | None]:
    """`LEAD(value, n)`: the value of the row n positions AFTER. Optional for the same reason."""
    return SnakeWindow[T | None](func="LEAD", arg=value, extra_args=(offset,))


def as_window(aggregate: SnakeAggregate[T]) -> SnakeWindow[T]:
    """Turns an aggregate into a window: `SUM(x)` -> `SUM(x) OVER (...)`.

    With GROUP BY it returns one row per group; as a window, every row with its running total. Used by `SnakeAggregate.over(...)`.
    """
    return SnakeWindow[T](func=aggregate.func.value, arg=aggregate.arg)


def has_window(value: object) -> bool:
    """Does this value contain a window function, however nested?

    It walks the nodes that WRAP another value (arithmetic, aggregate); the rest are leaves. It exists
    to REJECT the window where SQL forbids it: `WHERE row_number() + 1 > 3` is just as impossible as it is without the `+ 1`.
    """
    if isinstance(value, SnakeWindow):
        return True
    if isinstance(value, SnakeArith):
        return has_window(value.left) or has_window(value.right)
    if isinstance(value, SnakeAggregate):
        return value.arg is not None and has_window(value.arg)
    return False


class SnakeFrameMode(Enum):
    """`ROWS` counts ROWS, `RANGE` counts VALUES. With ties they answer differently.

    Offering only `ROWS` would be the smaller API and the wrong one: somebody ordering by a day that
    has several readings in it means RANGE, and handing them ROWS is a wrong answer with no error.
    """

    ROWS = "ROWS"
    RANGE = "RANGE"


@dataclass(frozen=True, slots=True)
class SnakeFrameBound:
    """One end of a frame. `offset=None` is UNBOUNDED; `offset=0` is the current row.

    The offset reaches the STATEMENT rather than `params`, and that is measured rather than lazy:
    PostgreSQL and SQLite take a placeholder in a bound and MariaDB rejects it outright, so the only
    portable spelling is the literal. It is safe for the same reason the JSON key path is — the value
    is an `int` from Python's own type system and it is checked when the bound is BUILT, before any
    SQL exists. An integer carries no injection.
    """

    offset: int | None
    following: bool

    def sql(self) -> str:
        """The bound as standard SQL. The three engines spell this identically (measured)."""
        direction = "FOLLOWING" if self.following else "PRECEDING"
        if self.offset is None:
            return f"UNBOUNDED {direction}"
        if self.offset == 0:
            return "CURRENT ROW"
        return f"{self.offset} {direction}"

    def rank(self) -> tuple[int, int]:
        """Where this bound sits on the timeline, so a frame can check it does not run backwards."""
        if self.offset is None:
            return (4, 0) if self.following else (0, 0)
        if self.offset == 0:
            return (2, 0)
        return (3, self.offset) if self.following else (1, -self.offset)


@dataclass(frozen=True, slots=True)
class SnakeFrame:
    """`<mode> BETWEEN <start> AND <end>`: which neighbouring rows the function may look at."""

    mode: SnakeFrameMode
    start: SnakeFrameBound
    end: SnakeFrameBound

    def sql(self) -> str:
        """The whole clause. No dialect involved: it is the same on the three engines."""
        return f"{self.mode.value} BETWEEN {self.start.sql()} AND {self.end.sql()}"


# The current row, which is the commonest end of a trailing window. A constant rather than a
# function because it takes no argument and there is exactly one of it.
SNAKE_CURRENT_ROW = SnakeFrameBound(offset=0, following=False)


def _bound(rows: int | None, following: bool) -> SnakeFrameBound:
    """Shared guard. Refusing here is what lets the number be interpolated later."""
    if rows is not None and rows < 0:
        raise SnakeValueError(
            f"A frame bound cannot be negative (got {rows}): the DIRECTION is the function you "
            f"call, so the distance is always counted forwards from here. For {abs(rows)} rows the "
            f"other way, call the other one."
        )
    return SnakeFrameBound(offset=rows, following=following)


def snake_preceding(rows: int | None = None) -> SnakeFrameBound:
    """`n PRECEDING`, or `UNBOUNDED PRECEDING` with no argument."""
    return _bound(rows, following=False)


def snake_following(rows: int | None = None) -> SnakeFrameBound:
    """`n FOLLOWING`, or `UNBOUNDED FOLLOWING` with no argument."""
    return _bound(rows, following=True)


def _frame(
    mode: SnakeFrameMode, start: SnakeFrameBound, end: SnakeFrameBound
) -> SnakeFrame:
    """Shared guard: a frame that ends before it starts is empty by construction."""
    if start.rank() > end.rank():
        raise SnakeValueError(
            f"This frame starts after it ends ({start.sql()} .. {end.sql()}), so it can never "
            f"contain a row. The engines reject it too — it is caught here so the complaint names "
            f"the frame instead of arriving from the driver."
        )
    return SnakeFrame(mode=mode, start=start, end=end)


def snake_rows(start: SnakeFrameBound, end: SnakeFrameBound) -> SnakeFrame:
    """`ROWS BETWEEN start AND end`: counts ROWS, so ties are separate rows."""
    return _frame(SnakeFrameMode.ROWS, start, end)


def snake_range(start: SnakeFrameBound, end: SnakeFrameBound) -> SnakeFrame:
    """`RANGE BETWEEN start AND end`: counts VALUES, so tied rows come in together."""
    return _frame(SnakeFrameMode.RANGE, start, end)
