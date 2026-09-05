"""`DATE_TRUNC` and `EXTRACT`, executed where the engine has them and refused where it does not.

This pair is the clearest case in the catalogue of a claim that a SQL-string test cannot make. The
string is the same everywhere; what differs is who will run it, and here that is two different
answers for two functions:

| function | Postgres | MySQL | SQLite |
|---|---|---|---|
| `DATE_TRUNC` | runs | refuses | refuses |
| `EXTRACT` | runs | runs | refuses |

So this file does both halves. Where the engine has the function it EXECUTES and reads the value
back; where it has not, it checks that asking produces a refusal that NAMES the function — because
a missing translation used to look exactly like a forgotten one, which is how `ABS` sat absent from
SQLite for as long as it did.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SnakeUtc,
    snake_datetime,
    snake_datetimetz,
    snake_int,
    snake_model,
)
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.expressions import snake_date_trunc, snake_extract
from snakeorm.expressions.scalar import SnakeDatePart, SnakeFunc
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="dx_events")
class Event(SnakeModel):
    """One instant, picked so the truncation and every part have a distinct answer."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    happened_at: SnakeColumn[datetime] = snake_datetime()
    # The SAME instant in the type the ORM actually recommends for a timestamp. The plain column
    # above is the easy case and it is the only one that was covered: the date functions took
    # `SnakeValue[datetime]`, and `SnakeValue[T]` is invariant, so `SnakeUtc` — a `datetime`
    # SUBCLASS — was refused by the checker while running perfectly. A column nobody could write
    # the query for is not a covered column.
    utc_at: SnakeColumn[SnakeUtc] = snake_datetimetz()


_WHEN = datetime(2026, 3, 14, 15, 9, 26)
_WHEN_UTC = SnakeUtc.of(_WHEN.replace(tzinfo=timezone.utc))


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with the same instant in them."""
    with three_sessions([Event]) as sessions:
        for session in sessions.values():
            session.add(Event(id=1, happened_at=_WHEN, utc_at=_WHEN_UTC))
            session.commit()
        yield sessions


def _extract(session: SnakeSession, part: SnakeDatePart) -> int:
    """One `EXTRACT` over the seeded row, as the engine answers it."""
    rows = session.select(SnakeQuery(Event), snake_extract(part, Event.happened_at))
    return int(rows[0][0])


@pytest.mark.parametrize("engine", ["postgres", "mysql"])
def test_extract_pulls_the_part_out_where_the_engine_has_it(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Year, month, day and hour come back as NUMBERS, and they are the ones that were stored."""
    session = engines[engine]

    assert _extract(session, SnakeDatePart.YEAR) == 2026
    assert _extract(session, SnakeDatePart.MONTH) == 3
    assert _extract(session, SnakeDatePart.DAY) == 14
    assert _extract(session, SnakeDatePart.HOUR) == 15


def test_date_trunc_cuts_the_instant_where_the_engine_has_it(
    engines: dict[str, SnakeSession],
) -> None:
    """Truncating to the month keeps the year and month and zeroes the rest. Postgres only."""
    session = engines["postgres"]

    rows = session.select(
        SnakeQuery(Event), snake_date_trunc(SnakeDatePart.MONTH, Event.happened_at)
    )
    truncated = rows[0][0]

    assert isinstance(truncated, datetime)
    assert (truncated.year, truncated.month, truncated.day) == (2026, 3, 1)
    assert (truncated.hour, truncated.minute, truncated.second) == (0, 0, 0)


@pytest.mark.parametrize(
    "engine, part",
    [("mysql", "DATE_TRUNC"), ("sqlite", "DATE_TRUNC"), ("sqlite", "EXTRACT")],
)
def test_the_engine_that_cannot_refuses_and_names_the_function(
    engine: str, part: str, engines: dict[str, SnakeSession]
) -> None:
    """Asking an engine for a function it has not raises, and the message NAMES it.

    The half that keeps the row honest. Leaving these engines simply absent would read like nobody
    had got round to them, which is indistinguishable from the bug this catalogue was built to make
    impossible — and the message has to carry the name, or the reader is left guessing which of the
    two functions in the expression the engine choked on.
    """
    dialect = engines[engine].dialect

    with pytest.raises(SnakeDialectError) as refusal:
        dialect.function_name(getattr(SnakeFunc, part))

    assert part in str(refusal.value)


@pytest.mark.parametrize("engine", ["postgres", "mysql"])
def test_extract_reads_the_orms_own_timestamp_type(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`EXTRACT` over a `SnakeUtc` column: the type the documentation tells you to store instants in.

    The column beside it is a plain `datetime` and it is the one that was already tested, which is
    how the hole survived — the functions worked, and the only thing you could not do was write the
    call. This asserts the runtime half, so a future change to the signature has to keep both.
    """
    session = engines[engine]
    rows = session.select(
        SnakeQuery(Event), snake_extract(SnakeDatePart.YEAR, Event.utc_at)
    )

    assert int(rows[0][0]) == 2026
