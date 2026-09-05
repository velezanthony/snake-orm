"""The UTC helpers against the THREE engines: the instant survives, whatever the zone it was written in.

The helpers had a unit test and the TYPE had a round trip; what nobody had asked is whether an
instant written from Madrid comes back as the same instant on an engine that keeps no zone at all.
That is the question the whole `SnakeUtc` design exists to answer, and it is a per-engine one:
Postgres has `TIMESTAMPTZ`, MySQL and SQLite do not, and both store what they are given.

The same shape as bug #39 — a fidelity claim held up on one engine — which is why it is asked here
rather than assumed from the type round trip.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SnakeUtc,
    snake_datetimetz,
    snake_int,
    snake_model,
)
from snakeorm.times import to_utc, utc_from_zone, utc_now
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@snake_model(table="utc_events")
class Event(SnakeModel):
    """An event stamped with an instant."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    happened_at: SnakeColumn[SnakeUtc] = snake_datetimetz()


# 14:30 in Madrid on a summer date is 12:30 UTC: the offset is +02:00 there, so a naive read of the
# wall clock would be two hours wrong and would still look like a plausible time.
_MADRID = datetime(2026, 7, 15, 14, 30, 0)
_SAME_INSTANT_UTC = datetime(2026, 7, 15, 12, 30, 0, tzinfo=UTC)


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with the table created and nothing written: each test stamps its own."""
    with three_sessions([Event]) as sessions:
        yield sessions


@pytest.mark.parametrize("engine", _ENGINES)
def test_an_instant_written_from_another_zone_comes_back_as_the_same_instant(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """THE assertion: 14:30 in Madrid is 12:30 UTC, and it is still 12:30 UTC after the round trip.

    An engine that dropped the offset would hand back 14:30 — a perfectly plausible time, two hours
    from the truth, and nothing would say so. That is why the comparison is against the instant and
    not against "it came back".
    """
    session = engines[engine]
    session.add(Event(id=1, happened_at=SnakeUtc.from_zone(_MADRID, "Europe/Madrid")))
    session.commit()

    stored = session.first(SnakeQuery(Event).filter(Event.id == 1))

    assert stored is not None
    assert stored.happened_at == _SAME_INSTANT_UTC, (
        f"{engine} gave back {stored.happened_at!r} instead of the instant that was written"
    )


@pytest.mark.parametrize("engine", _ENGINES)
def test_what_comes_back_is_aware_and_in_utc(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """A naive datetime is the bug this type exists to prevent, so it is asserted and not hoped for.

    MySQL and SQLite have no zone-carrying type at all: what they hold is what they were given. The
    guarantee therefore belongs to the ORM, and belongs on every engine or on none.
    """
    session = engines[engine]
    session.add(Event(id=1, happened_at=SnakeUtc.of(utc_now())))
    session.commit()

    stored = session.first(SnakeQuery(Event).filter(Event.id == 1))

    assert stored is not None
    assert stored.happened_at.tzinfo is not None, (
        f"{engine} handed back a NAIVE datetime"
    )
    assert stored.happened_at.utcoffset() == _SAME_INSTANT_UTC.utcoffset()


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_two_helpers_agree_on_the_same_instant(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`to_utc` and `utc_from_zone` are two doors to one wardrobe, and the engine must not tell them apart.

    Both rows are written from the same moment expressed differently; a filter that found one and
    not the other would mean the conversion happened after the comparison rather than before.
    """
    session = engines[engine]
    # Built with the ZONE, not with the tzinfo of an already-converted value: `utc_from_zone` hands
    # back a UTC datetime, so borrowing its `tzinfo` would give 14:30 UTC — the wrong moment,
    # arrived at by exactly the confusion these helpers exist to remove.
    aware = _MADRID.replace(tzinfo=ZoneInfo("Europe/Madrid"))

    session.add(
        Event(id=1, happened_at=SnakeUtc.of(utc_from_zone(_MADRID, "Europe/Madrid")))
    )
    session.add(Event(id=2, happened_at=SnakeUtc.of(to_utc(aware))))
    session.commit()

    found = session.all(
        SnakeQuery(Event)
        .filter(Event.happened_at == _SAME_INSTANT_UTC)
        .order_by(Event.id.asc())
    )

    assert [row.id for row in found] == [1, 2], (
        "the two helpers did not land on the same instant once the engine had it"
    )
