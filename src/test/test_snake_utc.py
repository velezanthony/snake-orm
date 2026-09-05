"""Tests for `SnakeUtc`: an instant in UTC that cannot be built wrong.

The guard that already exists shouts at SAVE time. That leaves a gap between writing the code and
finding out about the mistake, and in an ORM whose thesis is that illegal states cannot be written,
that is settling. `SnakeUtc` closes it: there is no way to manufacture one that is not in UTC, so
there is nothing left to check afterwards.

It subclasses `datetime` on purpose, and that is the whole design decision. Facing inwards, the
checker rejects `SnakeUtc = datetime.now(UTC)` because a `datetime` is not a `SnakeUtc`. Facing
outwards, a `SnakeUtc` IS a `datetime`, so DRF, Pydantic, Jinja or `json.dumps` never notice a
thing. A wrapper with the `datetime` inside would give you the first and lose the second.

The constructors exist because exactly two shapes arrive from outside, and only one carries the
instant:

    JS   `date.toISOString()`      "2026-06-01T12:30:00.000Z"   -> parse()      straight through
    HTML `<input datetime-local>`  "2026-06-01T14:30"           -> from_zone()  it must be placed
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from snakeorm import SnakeUtc
from snakeorm.core.exceptions import SnakeValueError

MADRID = timezone(timedelta(hours=2))


def test_it_is_a_datetime_for_everything_outside() -> None:
    """Checks that a `SnakeUtc` passes anywhere a `datetime` is expected.

    That is what makes it NOT viral: serializers, templates and third-party libraries check
    `isinstance(x, datetime)` and keep working without knowing this type exists.
    """
    moment = SnakeUtc.now()
    assert isinstance(moment, datetime)
    assert moment.isoformat().endswith("+00:00")
    assert json.dumps({"t": moment}, default=str)


def test_now_is_in_utc() -> None:
    """Checks that `SnakeUtc.now()` gives the current instant in UTC, with a zone."""
    assert SnakeUtc.now().utcoffset() == timedelta(0)


def test_the_constructor_defaults_to_utc() -> None:
    """Checks that building it with no zone does NOT give a naive one: it places it in UTC.

    A naive `SnakeUtc` would be a contradiction with a name on it, so it is not allowed to exist.
    """
    assert SnakeUtc(2026, 6, 1, 12, 30).utcoffset() == timedelta(0)


def test_the_constructor_refuses_another_zone() -> None:
    """Checks that building it with ANOTHER zone is rejected instead of converting behind the scenes.

    Converting here would be silent: you would ask for 14:30 in Madrid and the object would say
    12:30 without you asking for it. For converting there is `of()`, which is called on purpose.
    """
    with pytest.raises(SnakeValueError, match="of"):
        SnakeUtc(2026, 6, 1, 14, 30, tzinfo=MADRID)


def test_of_converts_an_aware_datetime() -> None:
    """Checks that `of()` re-expresses in UTC an instant that already has a zone, without moving it."""
    madrid = datetime(2026, 6, 1, 14, 30, tzinfo=MADRID)
    moment = SnakeUtc.of(madrid)
    assert moment == madrid  # the SAME moment
    assert moment.hour == 12  # written in UTC
    assert isinstance(moment, SnakeUtc)


def test_of_refuses_a_naive_datetime() -> None:
    """Checks that `of()` rejects a naive one: there is no instant to re-express."""
    with pytest.raises(SnakeValueError, match="from_zone"):
        SnakeUtc.of(datetime(2026, 6, 1, 14, 30))


def test_parse_reads_what_javascript_sends_directly() -> None:
    """Checks the JS path: `toISOString()` gives an ISO with `Z` and it is stored straight through.

    It is 90% of the real cases, and it requires knowing nothing about the user: the string already
    carries the instant.
    """
    moment = SnakeUtc.parse("2026-06-01T12:30:00.000Z")
    assert moment == datetime(2026, 6, 1, 12, 30, tzinfo=UTC)
    assert isinstance(moment, SnakeUtc)


def test_parse_accepts_any_offset_and_normalises_it() -> None:
    """Checks that an ISO with another offset also gets in: the instant is already defined.

    Converting here is NOT silent: you called `parse` precisely in order to get the UTC one.
    """
    assert SnakeUtc.parse("2026-06-01T14:30:00+02:00").hour == 12


def test_parse_shouts_when_the_string_has_no_zone() -> None:
    """Checks that an ISO WITHOUT a zone is rejected, which is what you asked for.

    It is exactly what `<input type="datetime-local">` sends: "2026-06-01T14:30". That string does
    not say where the time is from, so accepting it would force assuming a zone. The message points
    at `from_zone`, which is where the zone is supplied by whoever knows it.
    """
    with pytest.raises(SnakeValueError, match="from_zone"):
        SnakeUtc.parse("2026-06-01T14:30")


def test_from_zone_handles_the_html_form() -> None:
    """Checks the form path: local time + the user's zone -> instant in UTC."""
    from_the_form = "2026-06-01T14:30"  # what <input type="datetime-local"> sends
    moment = SnakeUtc.from_zone(datetime.fromisoformat(from_the_form), "Europe/Madrid")
    assert moment == datetime(2026, 6, 1, 12, 30, tzinfo=UTC)
    assert isinstance(moment, SnakeUtc)


def test_from_zone_honours_daylight_saving() -> None:
    """Checks that the zone is applied with its daylight saving, not with a fixed offset.

    The same 14:30 in Madrid is 12:30 UTC in June and 13:30 in January. A fixed offset would be
    right half the year, which is the worst class of bug: the one that only shows up in one season.
    """
    assert SnakeUtc.from_zone(datetime(2026, 6, 1, 14, 30), "Europe/Madrid").hour == 12
    assert SnakeUtc.from_zone(datetime(2026, 1, 1, 14, 30), "Europe/Madrid").hour == 13


def test_from_zone_rejects_an_unknown_zone() -> None:
    """Checks that a non-existent zone fails clearly and does not fall back to UTC in silence."""
    with pytest.raises(SnakeValueError, match="Europa/Madrid"):
        SnakeUtc.from_zone(datetime(2026, 6, 1, 14, 30), "Europa/Madrid")


def test_to_zone_gives_it_back_in_a_readable_zone() -> None:
    """Checks the return trip: to RENDER a date you need the zone of whoever is reading it.

    Storing in UTC and displaying in local time is the full cycle; without this, the output half
    would be missing and everyone would write it by hand.
    """
    moment = SnakeUtc(2026, 6, 1, 12, 30)
    local = moment.to_zone("Europe/Madrid")
    assert local.hour == 14
    assert local == moment  # it is still the same moment
