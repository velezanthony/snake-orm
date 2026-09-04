"""`literal()` must refuse a number it cannot write, instead of writing a bareword.

`literal()` did `str(value)` for anything numeric, so `float('inf')` came out as `inf` — with no
quotes. A VALUE turned into an IDENTIFIER: `snake_column(default=float('inf'))` emitted
`... DEFAULT inf`, which PostgreSQL reads as a reference to a column called `inf`.

On SQLite the DDL does not even fail. The table gets created and an INSERT leaves `('inf', 'text')`
in a column declared `REAL NOT NULL` — silent corruption, and it contradicts what
`docs/users/reference/limits.md` promises. Three lines below the bug there is already a
`SnakeDialectError` for values it does not know how to format; here it knew it did not know, and
returned a bareword anyway.

WHY REFUSE ON ALL THREE, when Postgres can in fact store an infinity. Two reasons, and the second is
the one that decides:

- Postgres accepts `DEFAULT 'Infinity'` in a `double precision` and SQLite stores a real infinity
  with `DEFAULT 9e999`, so an engine-by-engine rule IS possible for the infinities.
- It is NOT possible for `NaN`. SQLite loses it and Postgres does not, so the rule would have to be
  split by VALUE as well as by engine, inside the half of `literal()` that has no engine in it. Two
  axes of special case for a DDL default nobody writes on purpose.

This is a FORMATTER failure, not a capability one: `Cap.FLOAT_SPECIALS` already exists and Postgres
answers `Full()` to it. Sending it to the catalogue would say the engine cannot do something it can.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.dialects.base import SnakeDialect

_DIALECTS = [PostgresDialect(), MySQLDialect(), SQLiteDialect()]

_NOT_FINITE = [
    float("inf"),
    float("-inf"),
    float("nan"),
    Decimal("Infinity"),
    Decimal("-Infinity"),
    Decimal("NaN"),
    Decimal("sNaN"),
]


@pytest.mark.parametrize("dialect", _DIALECTS, ids=lambda d: type(d).__name__)
@pytest.mark.parametrize("value", _NOT_FINITE, ids=repr)
def test_a_non_finite_number_is_refused_instead_of_written_bare(
    dialect: SnakeDialect, value: object
) -> None:
    """Every dialect, every spelling. `str()` of each of these is a bareword, not a literal."""
    with pytest.raises(SnakeDialectError, match="finite"):
        dialect.literal(value)


@pytest.mark.parametrize("dialect", _DIALECTS, ids=lambda d: type(d).__name__)
def test_a_huge_int_is_still_a_number(dialect: SnakeDialect) -> None:
    """A Python `int` has no infinity, and the finiteness check must not be asked about one.

    `math.isfinite(10**400)` raises `OverflowError: int too large to convert to float`. A guard that
    ran it over every numeric value would kill a perfectly good `NUMERIC` default with an exception
    that is not even a `SnakeError` — a regression introduced BY the fix, on a value the engine
    stores without complaint.
    """
    assert dialect.literal(10**400) == str(10**400)


@pytest.mark.parametrize("dialect", _DIALECTS, ids=lambda d: type(d).__name__)
def test_ordinary_numbers_are_untouched(dialect: SnakeDialect) -> None:
    """The floor: the fix must not change how a normal number is written."""
    assert dialect.literal(42) == "42"
    assert dialect.literal(1.5) == "1.5"
    assert dialect.literal(Decimal("10.50")) == "10.50"
    assert dialect.literal(True) == ("TRUE" if dialect.literal(True) != "1" else "1")
