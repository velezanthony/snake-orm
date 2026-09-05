"""How a NUMBER is written as a SQL literal, in one place for the three dialects.

The DDL door: where a value cannot be a placeholder — a `DEFAULT`, a `CHECK`, the `WHERE` of a
partial index. Everything else goes out parametrised, which is why this file is small and why what
it gets wrong is expensive.

It used to be `str(value)`, so `float('inf')` came out as bare `inf` — an IDENTIFIER. Postgres reads
`DEFAULT inf` as a column reference; SQLite creates the table and hands back `('inf', 'text')` from
a `REAL NOT NULL`.
"""

from __future__ import annotations

import math
from decimal import Decimal

from snakeorm.core.exceptions import SnakeDialectError


def numeric_literal(value: int | float | Decimal, dialect_name: str) -> str:
    """The SQL literal of a number, or a refusal if it has no literal to be written as.

    `int` returns FIRST because `math.isfinite` on a big one raises `OverflowError`, which would
    kill a `NUMERIC` default the engine stores happily.

    The refusal spans the three engines instead of splitting per engine, and `NaN` is why: the
    infinities have per-engine literals, but SQLite loses a `NaN` and Postgres does not — so the
    rule would have to split by VALUE as well, inside the half of `literal()` that has no engine in
    it. It is a formatter failure, not a capability one: `Cap.FLOAT_SPECIALS` exists and Postgres
    answers `Full()` to it.
    """
    if isinstance(value, int):
        return str(value)
    # `Decimal` asks ITSELF, because `math.isfinite` cannot look at all of them:
    # `math.isfinite(Decimal('sNaN'))` raises `ValueError: cannot convert signaling NaN to float`,
    # so the guard would blow up with the wrong exception on the one value most likely to have got
    # there by accident.
    finite = value.is_finite() if isinstance(value, Decimal) else math.isfinite(value)
    if not finite:
        raise SnakeDialectError(
            f"{dialect_name} has no SQL literal for {value!r}: a DDL literal has to be finite. "
            f"`str()` of it is a bareword —`inf`, `NaN`— which an engine reads as an identifier, "
            f"not as a value, and SQLite accepts it into a REAL column as text without complaining. "
            f"Store it through a parametrised write instead, where the driver types it properly."
        )
    return str(value)
