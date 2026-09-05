"""Tests for the date helpers: creating and converting to UTC without guessing zones.

They exist because the ORM is going to REJECT a `datetime` that is not in UTC in a column with a
zone. A guard that forbids without offering the way out is a half guard: the rest of the project's
errors say what to do (*"Cuantízalo tú (value.quantize(...))"*), and this one has to be able to say
it too.

The case that justifies them is not theoretical, it is the form: `<input type="datetime-local">`
sends `"2026-06-01T14:30"` —WITHOUT a zone, in the local time of whoever filled it in— and JS sends
`"2026-06-01T12:30:00.000Z"`, which already comes in UTC. They are the two extremes: one has to be
placed in a zone to know which instant it is, and the other already knows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from snakeorm import parse_utc, to_utc, utc_from_zone, utc_now
from snakeorm.core.exceptions import SnakeValueError

MADRID = timezone(timedelta(hours=2))  # +02:00, mainland Spanish summer time


def test_utc_now_is_aware_and_in_utc() -> None:
    """Checks that `utc_now()` returns an instant WITH a zone, and that the zone is UTC.

    A bare `datetime.now()` returns a naive one: the starting mistake that has to be avoided.
    """
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_to_utc_converts_an_aware_datetime() -> None:
    """Checks that `to_utc()` re-expresses an instant in UTC without moving it."""
    madrid = datetime(2026, 6, 1, 14, 30, tzinfo=MADRID)
    converted = to_utc(madrid)
    assert converted == madrid  # the SAME instant
    assert converted.utcoffset() == timedelta(0)
    assert converted.hour == 12  # and written in UTC it is 12:30


def test_to_utc_leaves_an_utc_datetime_alone() -> None:
    """Checks that converting something already in UTC is a no-op."""
    already = datetime(2026, 6, 1, 12, 30, tzinfo=UTC)
    assert to_utc(already) == already


def test_to_utc_refuses_a_naive_datetime() -> None:
    """Checks that `to_utc()` REJECTS a naive one instead of assuming a zone for it.

    This is the heart of the whole thing: a `datetime` without a zone identifies no instant.
    Converting it would require guessing where it is from, and guessing is precisely what this ORM
    does not do. That is what `utc_from_zone()` is for, where YOU supply the zone.
    """
    with pytest.raises(
        SnakeValueError, match="has no zone, so it identifies no instant"
    ):
        to_utc(datetime(2026, 6, 1, 14, 30))


def test_utc_from_zone_places_a_naive_datetime_and_converts_it() -> None:
    """Checks that `utc_from_zone()` places a local time in its zone and yields the UTC one.

    It is THE form tool: `<input type="datetime-local">` sends "2026-06-01T14:30" with no zone, and
    only whoever knows the user knows which zone that time belongs to.
    """
    assert utc_from_zone(datetime(2026, 6, 1, 14, 30), "Europe/Madrid") == datetime(
        2026, 6, 1, 12, 30, tzinfo=UTC
    )


def test_utc_from_zone_honours_daylight_saving() -> None:
    """Checks that the zone is applied with its daylight saving, not with a fixed offset.

    The same 14:30 in Madrid is 12:30 UTC in June and 13:30 UTC in January. A fixed offset would get
    one of the two wrong, and it would be the kind of bug that only shows up half the year.
    """
    assert utc_from_zone(datetime(2026, 6, 1, 14, 30), "Europe/Madrid").hour == 12
    assert utc_from_zone(datetime(2026, 1, 1, 14, 30), "Europe/Madrid").hour == 13


def test_utc_from_zone_refuses_an_aware_datetime() -> None:
    """Checks that placing in a zone something that ALREADY has one is rejected.

    It would be ambiguous: is it reinterpreted or converted? Both readings are reasonable and give
    different results, so `to_utc()` is required explicitly for the second one.
    """
    with pytest.raises(SnakeValueError, match="already has a zone"):
        utc_from_zone(datetime(2026, 6, 1, 14, 30, tzinfo=MADRID), "Europe/Madrid")


def test_utc_from_zone_rejects_an_unknown_zone() -> None:
    """Checks that a non-existent zone fails clearly and does not fall back to UTC in silence."""
    with pytest.raises(SnakeValueError, match="Europa/Madrid"):
        utc_from_zone(datetime(2026, 6, 1, 14, 30), "Europa/Madrid")


def test_parse_utc_reads_what_javascript_sends() -> None:
    """Checks that the ISO-8601 with `Z` produced by `Date.toISOString()` in JS is read.

    It is what arrives in a JSON from the browser, and it already comes in UTC: it just has to be
    read.
    """
    assert parse_utc("2026-06-01T12:30:00.000Z") == datetime(
        2026, 6, 1, 12, 30, tzinfo=UTC
    )


def test_parse_utc_converts_a_string_with_another_offset() -> None:
    """Checks that an ISO with another offset is re-expressed in UTC (the instant is already fixed)."""
    assert parse_utc("2026-06-01T14:30:00+02:00") == datetime(
        2026, 6, 1, 12, 30, tzinfo=UTC
    )


def test_parse_utc_refuses_a_string_without_a_zone() -> None:
    """Checks that an ISO WITHOUT a zone is rejected: it is what `<input type="datetime-local">` sends.

    The message has to point at `utc_from_zone()`, because that text does not say where the time is
    from and only whoever knows the user can say it.
    """
    with pytest.raises(SnakeValueError, match="utc_from_zone"):
        parse_utc("2026-06-01T14:30")


def test_parse_utc_refuses_something_that_is_not_a_date() -> None:
    """Checks that a text which is not a date fails as `SnakeValueError`, not as ValueError.

    The caller already catches the ORM's errors; forcing them to catch the stdlib's on top would be
    leaking the guts.
    """
    with pytest.raises(
        SnakeValueError, match="Something like '2026-06-01T12:30:00Z' or"
    ):
        parse_utc("tomorrow afternoon")
