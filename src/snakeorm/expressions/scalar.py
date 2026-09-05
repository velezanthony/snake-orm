"""Scalar text and date functions (`LOWER`, `TRIM`, `DATE_TRUNC`, `EXTRACT`...).

A single node (`SnakeFunc`) with an agnostic enum instead of one class per function: a new node
would be one more place to forget something. The dialect translates the names. The TYPE is pinned
down by the constructors (`snake_length(User.name)` is `SnakeValue[int]`), typing the projection
with no `Any`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.expressions.expression import CASTABLE, SnakeCast, SnakeValue

T = TypeVar("T")
V = TypeVar("V")


class SnakeFunc(Enum):
    """Supported scalar functions, with agnostic names that the dialect translates."""

    LOWER = "lower"
    UPPER = "upper"
    TRIM = "trim"
    LENGTH = "length"
    CONCAT = "concat"
    DATE_TRUNC = "date_trunc"
    EXTRACT = "extract"
    ABS = "abs"
    ROUND = "round"
    SUBSTRING = "substring"
    REPLACE = "replace"
    CEIL = "ceil"
    FLOOR = "floor"
    SQRT = "sqrt"
    POWER = "power"


class SnakeDatePart(Enum):
    """A part of a date, for `DATE_TRUNC` and `EXTRACT`. Standard SQL names."""

    YEAR = "year"
    QUARTER = "quarter"
    MONTH = "month"
    WEEK = "week"
    DAY = "day"
    HOUR = "hour"
    MINUTE = "minute"
    SECOND = "second"


@dataclass(frozen=True, slots=True, eq=False)
class SnakeFuncCall(SnakeValue[T]):
    """A call to a scalar function: `FUNC(arg, ...)`.

    It is a VALUE (it gets compared, projected, aggregated). `part` is only used by the date
    functions and travels separately (in SQL, `EXTRACT(year FROM col)` is not a normal argument).
    """

    func: SnakeFunc
    arguments: tuple[SnakeValue[object] | object, ...]
    part: SnakeDatePart | None = None

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """Paths of the arguments that are columns, so the planner sees their JOINs."""
        return tuple(
            path
            for argument in self.arguments
            if isinstance(argument, SnakeValue)
            for path in argument.paths()
        )


def snake_lower(value: SnakeValue[str]) -> SnakeFuncCall[str]:
    """`LOWER(value)`."""
    return SnakeFuncCall(SnakeFunc.LOWER, (value,))


def snake_upper(value: SnakeValue[str]) -> SnakeFuncCall[str]:
    """`UPPER(value)`."""
    return SnakeFuncCall(SnakeFunc.UPPER, (value,))


def snake_trim(value: SnakeValue[str]) -> SnakeFuncCall[str]:
    """`TRIM(value)`: strips the whitespace off both ends."""
    return SnakeFuncCall(SnakeFunc.TRIM, (value,))


def snake_length(value: SnakeValue[str]) -> SnakeFuncCall[int]:
    """`LENGTH(value)`: returns an INTEGER, not text. That is the whole point of the typing."""
    return SnakeFuncCall(SnakeFunc.LENGTH, (value,))


def snake_concat(*values: SnakeValue[str] | str) -> SnakeFuncCall[str]:
    """`CONCAT(a, b, ...)`. Unlike `||`, it ignores NULLs instead of propagating them."""
    return SnakeFuncCall(SnakeFunc.CONCAT, values)


D = TypeVar("D", bound=datetime)
"""The datetime a date function was handed, kept instead of flattened.

`SnakeValue[T]` is INVARIANT, so a parameter annotated `SnakeValue[datetime]` rejects a
`SnakeValue[SnakeUtc]` even though `SnakeUtc` is a `datetime` subclass and the call runs fine. That
left the ORM's own recommended timestamp type unable to use the date functions, with no cast to
reach for: `CASTABLE` is `int`, `float`, `bool`.

Bounded rather than free, because `EXTRACT` over a `str` is a different mistake and one worth
keeping.
"""


def snake_date_trunc(part: SnakeDatePart, value: SnakeValue[D]) -> SnakeFuncCall[D]:
    """`DATE_TRUNC('part', value)`: trims the date to the given precision (grouping by month).

    It gives back the type it was handed. Trimming a timestamp to the month does not change what
    KIND of thing it is, so a `SnakeUtc` column keeps coming out a `SnakeUtc` — the alternative
    would hand back a plain `datetime` and lose the guarantee the column was declared for.
    """
    return SnakeFuncCall(SnakeFunc.DATE_TRUNC, (value,), part=part)


def snake_extract(part: SnakeDatePart, value: SnakeValue[D]) -> SnakeFuncCall[int]:
    """`EXTRACT(part FROM value)`: pulls out one component as a NUMBER (the year, the month...)."""
    return SnakeFuncCall(SnakeFunc.EXTRACT, (value,), part=part)


def snake_abs(value: SnakeValue[T]) -> SnakeFuncCall[T]:
    """`ABS(value)`: keeps the numeric type of its argument."""
    return SnakeFuncCall(SnakeFunc.ABS, (value,))


def snake_round(value: SnakeValue[T], digits: int = 0) -> SnakeFuncCall[T]:
    """`ROUND(value)`, or `ROUND(value, digits)` when digits are asked for.

    The zero is NOT passed through, and that is not tidiness. Postgres has `ROUND(double precision)`
    and `ROUND(numeric, int)` but no `ROUND(double precision, int)`, so emitting the second argument
    unasked made `snake_round()` on a float column fail there while working on the other two — for
    the default call, the one nobody would think to test on three engines. `ROUND(x)` means the same
    thing on all three.

    Asking for digits DOES work on all three now. Postgres has no `ROUND(double precision, int)`,
    so it declares the type its two-argument form wants —`syntax.round_casts_first_argument_to`— and
    the emitter casts. A SHAPE difference, translated, never stopping the plan.
    """
    if digits:
        return SnakeFuncCall(SnakeFunc.ROUND, (value, digits))
    return SnakeFuncCall(SnakeFunc.ROUND, (value,))


def snake_cast(value: SnakeValue[Any], as_type: type[V]) -> SnakeCast[V]:
    """`CAST(value AS <type>)`: an EXPLICIT change of type, named by whoever writes it.

    THE ORM DOES NOT PROMOTE, and this is the door that makes that stance liveable. The arithmetic
    operators carry one single `T` for both operands and the result, so `Stock.reserved /
    Stock.on_hand` is an `int` — which is what SQL does, and sometimes what you want. When it is not,
    you say so:

        snake_cast(Stock.reserved, float) / Stock.on_hand   ->  SnakeArith[float]

    `as_type` is what the RESULT is typed as, so the conversion travels through the type system
    instead of around it. The SQL name of that type is the dialect's business: measured, SQLite needs
    `REAL` where `NUMERIC` would answer 0.

    The whitelist refuses by name at the CALL SITE rather than at emission, which is where a refusal
    is worth something: the alternative is SQL the engine rejects and a driver explaining a decision
    this ORM made.
    """
    if as_type not in CASTABLE:
        raise SnakeUnsupportedFeature(
            f"There is no cast to {getattr(as_type, '__name__', as_type)!r}: an explicit cast "
            f"targets one of {', '.join(t.__name__ for t in CASTABLE)}. This is a whitelist and not "
            f"an oversight — a type the dialects cannot spell would be emitted as SQL the engine "
            f"rejects, and the complaint would arrive from the driver rather than from here."
        )
    return SnakeCast(source=value, as_type=as_type)


# What a date can be shifted by. A WHITELIST built by removing from `SnakeDatePart`, not a second
# enum: a quarter is a real thing to TRUNCATE to and not a thing any of the three engines spells as
# an interval, so it is refused by name rather than silently translated into three months.
SHIFTABLE: tuple[SnakeDatePart, ...] = (
    SnakeDatePart.YEAR,
    SnakeDatePart.MONTH,
    SnakeDatePart.WEEK,
    SnakeDatePart.DAY,
    SnakeDatePart.HOUR,
    SnakeDatePart.MINUTE,
    SnakeDatePart.SECOND,
)


@dataclass(frozen=True, slots=True, eq=False)
class SnakeDateShift(SnakeValue[T]):
    """Moving a date or a timestamp by a fixed amount: `placed_on + 30 days`.

    ONE node for both directions: subtracting is adding a negative `amount`, which the three engines
    accept and which keeps the sign in the VALUE instead of in a second node. `T` is the type of the
    SOURCE — shifting a date gives a date.

    The three spellings share nothing (`+ INTERVAL`, `DATE_ADD`, a modifier string), so the SQL is
    the dialect's business. It is the clearest case in the whole ORM for that seam.
    """

    value: SnakeValue[Any]
    amount: int
    unit: SnakeDatePart

    def paths(self) -> tuple[tuple[str, ...], ...]:
        """What it shifts: the amount is a literal and contributes no navigation of its own."""
        return self.value.paths()


def _shift(value: SnakeValue[T], amount: int, unit: SnakeDatePart) -> SnakeDateShift[T]:
    """Shared guard for both directions: the unit has to be one a date can actually move by."""
    if unit not in SHIFTABLE:
        raise SnakeUnsupportedFeature(
            f"A date cannot be shifted by {unit.name}: no engine spells it as an interval. "
            f"`SnakeDatePart` is shared with DATE_TRUNC and EXTRACT, where {unit.name} is real. "
            f"Shift by one of {', '.join(part.name for part in SHIFTABLE)} — a quarter is three "
            f"MONTHs, and writing that out is the caller's decision rather than a silent rewrite."
        )
    return SnakeDateShift(value=value, amount=amount, unit=unit)


def snake_date_add(
    value: SnakeValue[T], amount: int, unit: SnakeDatePart
) -> SnakeDateShift[T]:
    """Moves a date FORWARD: `snake_date_add(Order.placed_on, 30, SnakeDatePart.DAY)`.

    CALENDAR UNITS ARE NOT PORTABLE and the ORM says so rather than hiding it. Measured, `2026-01-31`
    plus one month is `2026-02-28` on PostgreSQL and MySQL —both clamp— and `2026-03-03` on SQLite,
    which overflows. That divergence is declared as `Cap.CALENDAR_INTERVAL`, so the session warns
    once instead of letting whichever engine the developer happens to run be the one that gets
    tested. DAY, HOUR, MINUTE, SECOND and WEEK are a fixed span and identical on all three.

    Emulating the clamp was the alternative, and it is the wrong one: the ORM would be computing
    dates in Python behind an expression that claims to be SQL.
    """
    return _shift(value, amount, unit)


def snake_date_sub(
    value: SnakeValue[T], amount: int, unit: SnakeDatePart
) -> SnakeDateShift[T]:
    """Moves a date BACKWARD. Same node with the sign flipped, because that is all it is."""
    return _shift(value, -amount, unit)


def snake_substring(
    value: SnakeValue[str], start: int, length: int
) -> SnakeFuncCall[str]:
    """`SUBSTRING(value, start, length)`: a slice of text, counted from ONE like SQL does.

    The bounds are VALUES and travel as parameters, which is not obvious enough to leave unsaid: a
    slice computed from user input with the numbers written into the statement is the shape an
    injection takes when nobody is looking at strings.
    """
    return SnakeFuncCall(SnakeFunc.SUBSTRING, (value, start, length))


def snake_replace(value: SnakeValue[str], old: str, new: str) -> SnakeFuncCall[str]:
    """`REPLACE(value, old, new)`: every occurrence, not the first. Both strings are parameters."""
    return SnakeFuncCall(SnakeFunc.REPLACE, (value, old, new))


def snake_ceil(value: SnakeValue[T]) -> SnakeFuncCall[T]:
    """`CEIL(value)`: rounds UP, keeping the type of its argument.

    `T -> T` and not `-> int`, and that was measured rather than assumed: `CEIL(1.2)` answers `2` on
    PostgreSQL and MySQL and `2.0` on SQLite. Declaring `int` would be false on one engine of three,
    which is the exact family of bug the integer-division work removed. Keeping the argument's type
    is true everywhere — a float in, a float back.
    """
    return SnakeFuncCall(SnakeFunc.CEIL, (value,))


def snake_floor(value: SnakeValue[T]) -> SnakeFuncCall[T]:
    """`FLOOR(value)`: rounds DOWN, keeping the type of its argument. Same measurement as `CEIL`."""
    return SnakeFuncCall(SnakeFunc.FLOOR, (value,))


def snake_sqrt(value: SnakeValue[Any]) -> SnakeFuncCall[float]:
    """`SQRT(value)`: always a float. Measured `double precision` on PostgreSQL and a real on SQLite."""
    return SnakeFuncCall(SnakeFunc.SQRT, (value,))


def snake_power(value: SnakeValue[Any], exponent: float) -> SnakeFuncCall[float]:
    """`POWER(value, exponent)`: always a float, and the exponent travels as a parameter."""
    return SnakeFuncCall(SnakeFunc.POWER, (value, exponent))
