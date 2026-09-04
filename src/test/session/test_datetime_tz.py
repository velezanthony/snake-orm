"""Tests that a `datetime` column says whether it carries a zone, and that zoned means UTC ONLY.

Two failures that were there, measured before writing this:

1. A NAIVE `datetime` walked right into a `TIMESTAMPTZ` column and came back naive. The type
   promised an instant with a zone and returned something that identifies no instant at all.
2. An aware one with another offset was stored AS IS. But `TIMESTAMPTZ` does not store the offset,
   it stores the instant: Postgres returns `12:30+00:00` where SQLite returns `14:30+02:00`. The
   same moment, and `.hour` is 12 or 14 depending on the engine. Anyone formatting the date gets
   different things in development and in production.

What says which of the two things a column stores is the TYPE, not a knob:

    SnakeColumn[SnakeUtc]   an INSTANT       -> TIMESTAMPTZ, UTC only
    SnakeColumn[datetime]   a WALL-CLOCK     -> TIMESTAMP, naive only

With a knob, the type and the declarator would both be saying the same thing and could contradict
each other: two sources of truth, one of them can lie. It is the exact reason `nullable=` was
removed.

And the type says it louder: a `SnakeUtc` cannot be built outside UTC, so the error shows up in the
editor. These guards are the runtime net, for whoever skips past the checker.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from snakeorm import (
    PostgresDialect,
    SQLiteDialect,
    SnakeColumn,
    SnakeModel,
    SnakeSession,
    SnakeUtc,
    snake_datetime,
    snake_datetimetz,
    snake_int,
    snake_model,
)
from snakeorm.core.exceptions import SnakeValueError
from snakeorm.migration.ddl import sql_type_of
from snakeorm.registry import registry

MADRID = timezone(timedelta(hours=2))


@snake_model(table="events_tz")
class Event(SnakeModel):
    """An instant (zoned) and a wall-clock time (unzoned), which are different things."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    ocurrio: SnakeColumn[SnakeUtc] = snake_datetimetz()
    apertura: SnakeColumn[datetime] = snake_datetime()


class _Driver:
    """Mute driver: the guard has to fire BEFORE anything reaches the database."""

    def fetch_all(self, sql: str, params: object) -> list[tuple[object, ...]]:
        return []

    def fetch_iter(self, sql: str, params: object, *, chunk: int = 1000):  # type: ignore[no-untyped-def]
        yield from ()

    def execute(self, sql: str, params: object) -> int:
        return 1

    @property
    def last_insert_id(self) -> int:
        return 1

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


@pytest.fixture
def session() -> SnakeSession:
    """Session over the mute driver."""
    return SnakeSession(_Driver(), SQLiteDialect())


def _event(**cambios: object) -> Event:
    """A valid event, with whichever fields are asked for replaced."""
    fields: dict[str, object] = {
        "id": 1,
        "ocurrio": SnakeUtc(2026, 6, 1, 12, 30),
        "apertura": datetime(2026, 6, 1, 9, 0),
    }
    fields.update(cambios)
    return Event(**fields)  # type: ignore[arg-type]


def test_a_snake_utc_column_emits_a_timestamp_with_zone() -> None:
    """Verifies that `SnakeColumn[SnakeUtc]` emits `TIMESTAMPTZ`: the type says it is an instant."""
    column = registry.table_of(Event).get_column("ocurrio")  # type: ignore[union-attr]
    assert column is not None
    assert sql_type_of(column, PostgresDialect()) == "TIMESTAMPTZ"


def test_a_plain_datetime_column_emits_a_timestamp_without_zone() -> None:
    """Verifies that `SnakeColumn[datetime]` emits `TIMESTAMP`, with no zone.

    It is what the documentation promised —"if you want one without a zone, declare it on purpose"—
    and did not exist: EVERY `datetime` went to `TIMESTAMPTZ` and there was no way to ask for else.
    """
    column = registry.table_of(Event).get_column("apertura")  # type: ignore[union-attr]
    assert column is not None
    assert sql_type_of(column, PostgresDialect()) == "TIMESTAMP"


def test_an_utc_datetime_is_accepted(session: SnakeSession) -> None:
    """Verifies that what the column promises —an instant in UTC— walks in unobstructed."""
    session.add(_event())


def test_a_naive_datetime_is_rejected_by_a_zoned_column(session: SnakeSession) -> None:
    """Verifies that a naive one does NOT get into a zoned column.

    Storing it would force us to assume which zone that time belongs to, and assuming is inventing.
    """
    with pytest.raises(SnakeValueError, match=r"stores an instant \(with a zone\)"):
        session.add(_event(ocurrio=datetime(2026, 6, 1, 14, 30)))


def test_a_non_utc_datetime_is_rejected_by_a_zoned_column(
    session: SnakeSession,
) -> None:
    """Verifies that an aware one with ANOTHER offset is rejected, and the message says how to fix.

    It is a perfectly well-defined instant, yes. But `TIMESTAMPTZ` does not store the offset:
    Postgres would give it back in UTC and SQLite in the original offset, so `.hour` would change
    with the engine. It is demanded at the door so that what you read is what you wrote.
    """
    with pytest.raises(SnakeValueError, match="to_utc"):
        session.add(_event(ocurrio=datetime(2026, 6, 1, 14, 30, tzinfo=MADRID)))


def test_a_naive_datetime_is_accepted_by_a_zoneless_column(
    session: SnakeSession,
) -> None:
    """Verifies that a `tz=False` column does accept the wall-clock time, its whole reason to be."""
    session.add(_event(apertura=datetime(2026, 6, 1, 9, 0)))


def test_an_aware_datetime_is_rejected_by_a_zoneless_column(
    session: SnakeSession,
) -> None:
    """Verifies that an aware one does NOT get into a column with no zone.

    Storing it would throw away the `tzinfo` and with it the instant: the silent failure the note in
    the columns guide has been describing from the start ("it gives you the wrong time, no crash").
    """
    with pytest.raises(SnakeValueError, match="SnakeUtc"):
        session.add(_event(apertura=datetime(2026, 6, 1, 9, 0, tzinfo=MADRID)))


def test_precision_reaches_the_ddl() -> None:
    """Verifies that `precision=` emits the engine's fractional-second digits.

    It is the only thing the TYPE cannot say, and that is why it is the only thing left as a
    parameter: `TIMESTAMPTZ(0)` means whole seconds and `(3)` milliseconds.
    """

    @snake_model(table="events_precision")
    class ConPrecision(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        al_segundo: SnakeColumn[SnakeUtc] = snake_datetimetz(precision=0)
        al_milis: SnakeColumn[datetime] = snake_datetime(precision=3)

    table = registry.table_of(ConPrecision)
    assert table is not None
    pg = PostgresDialect()
    assert sql_type_of(table.get_column("al_segundo"), pg) == "TIMESTAMPTZ(0)"  # type: ignore[arg-type]
    assert sql_type_of(table.get_column("al_milis"), pg) == "TIMESTAMP(3)"  # type: ignore[arg-type]
