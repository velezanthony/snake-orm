"""Date tooling: building and converting to UTC without anyone guessing a zone.

A zone-aware `datetime` column accepts UTC ONLY, and the ORM rejects anything else. This is the
other half of that rule: the way through, which a guard that forbids has to offer.

Why UTC is demanded instead of converting internally: `TIMESTAMPTZ` **does not store the offset**, it
stores the instant. If the ORM accepted `14:30+02:00`, Postgres would return `12:30+00:00` and SQLite
`14:30+02:00` — the same instant written differently, so `.hour` would be 12 or 14 depending on the
engine. By demanding UTC at the door, what you write is exactly what you read, on both.

Where dates come from in practice, which is what decides which tool is needed:

    JS   `date.toISOString()`      ->  "2026-06-01T12:30:00.000Z"   already UTC -> parse_utc()
    HTML `<input datetime-local>`  ->  "2026-06-01T14:30"           NO zone     -> utc_from_zone()

The second is the one that matters: that text does not say where the time is from. Only someone who
knows the user can, so the caller supplies the zone and never the ORM.
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from snakeorm.core.exceptions import SnakeValueError


def utc_now() -> datetime:
    """The current instant, WITH a zone and in UTC.

    It exists so nobody has to remember: a bare `datetime.now()` returns a naive one, which is the
    value the ORM is going to reject. A `utc_now()` that reads at a glance saves the round trip.
    """
    return datetime.now(UTC)


def to_utc(value: datetime) -> datetime:
    """Re-expresses in UTC an instant that ALREADY has a zone. It does not move it: only rewrites it.

    It rejects a naive one on purpose. A `datetime` with no zone identifies no instant — the same
    14:30 are different moments in Madrid and in Bogota — so converting it would mean GUESSING where
    it is from. `utc_from_zone()` is there for that, where the zone comes from whoever knows it.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise SnakeValueError(
            f"{value!r} has no zone, so it identifies no instant: the same 14:30 are different "
            f"moments in Madrid and in Bogota. If you know which zone that time is from, use "
            f"utc_from_zone(value, 'Europe/Madrid'); if it comes from a client, have it send you "
            f"the offset."
        )
    return value.astimezone(UTC)


def utc_from_zone(value: datetime, zone: str) -> datetime:
    """Places a LOCAL time in its zone and returns the instant in UTC.

        utc_from_zone(datetime(2026, 6, 1, 14, 30), "Europe/Madrid")   # -> 12:30 UTC

    It is the form's tool: `<input type="datetime-local">` sends "2026-06-01T14:30" with no zone. The
    zone is applied with its DAYLIGHT SAVING (`ZoneInfo`, not a fixed offset): the same 14:30 in
    Madrid are 12:30 UTC in June and 13:30 in January, and a fixed offset would be right half the
    year.

    It rejects a `datetime` that already has a zone: it would be ambiguous between reinterpreting and
    converting, two reasonable readings with different results. `to_utc()` is there to convert.
    """
    if value.tzinfo is not None:
        raise SnakeValueError(
            f"{value!r} already has a zone ({value.tzinfo}), so placing it in {zone!r} is "
            f"ambiguous: there is no telling whether you want to reinterpret the time or convert "
            f"the instant. To convert, to_utc(value)."
        )
    try:
        info = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise SnakeValueError(
            f"{zone!r} is not a known time zone. IANA database names are expected, such as "
            f"'Europe/Madrid' or 'America/Bogota'."
        ) from error
    return value.replace(tzinfo=info).astimezone(UTC)


def parse_utc(text: str) -> datetime:
    """Reads an ISO-8601 WITH a zone and returns the instant in UTC.

        parse_utc("2026-06-01T12:30:00.000Z")     # what JS sends with toISOString()
        parse_utc("2026-06-01T14:30:00+02:00")    # another offset: re-expressed in UTC

    It rejects text with no zone — what `<input type="datetime-local">` sends — because that text does
    not say where the time is from, and the ORM is not going to assume it.
    """
    # `fromisoformat` accepts the `Z` from 3.11 onwards, which is the project's floor.
    try:
        value = datetime.fromisoformat(text)
    except ValueError as error:
        raise SnakeValueError(
            f"{text!r} is not an ISO-8601 date. Something like "
            f"'2026-06-01T12:30:00Z' or '2026-06-01T14:30:00+02:00' is expected."
        ) from error
    if value.tzinfo is None:
        raise SnakeValueError(
            f"{text!r} carries no zone, so it identifies no instant. It is what an "
            f"<input type='datetime-local'> sends: if you know which zone that time is from, use "
            f"utc_from_zone(datetime.fromisoformat({text!r}), 'Europe/Madrid')."
        )
    return value.astimezone(UTC)


class SnakeUtc(datetime):
    """An instant in UTC. There is no way to build one that is not.

        created: SnakeColumn[SnakeUtc] = snake_datetimetz()

    It is a SUBCLASS of `datetime`, and the whole design decision sits right there:

    - Facing inwards, the checker rejects `SnakeUtc = datetime.now(UTC)`, because a `datetime` is not
      a `SnakeUtc`. The error shows up in the editor, not when saving.
    - Facing outwards, a `SnakeUtc` IS a `datetime`: `isinstance`, `isoformat()`, `astimezone()`, the
      DRF or Pydantic serialisers and the templates all keep working without noticing.

    A wrapper keeping the `datetime` inside would give the first and lose the second: every library
    in the stack would have to be taught the type.

    Two shapes arrive from outside, and only one carries the instant:

        JS   `date.toISOString()`      "2026-06-01T12:30:00.000Z"   -> parse()      direct
        HTML `<input datetime-local>`  "2026-06-01T14:30"           -> from_zone()  must be placed

    The second cannot be resolved on its own: that string does not say where the time is from. Only
    someone who knows the user does, so the caller supplies the zone.
    """

    __slots__ = ()

    def __new__(
        cls,
        year: int,
        month: int = 1,
        day: int = 1,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        microsecond: int = 0,
        tzinfo: tzinfo | None = None,
        *,
        fold: int = 0,
    ) -> SnakeUtc:
        """Builds the instant: with no zone it places it in UTC, and with another zone it RAISES.

        Converting here would be silent: you would ask for 14:30 in Madrid and the object would say
        12:30 without you having asked. `of()` is there to convert, and it is called on purpose.

        The signature is written out in full (rather than `*args`) so the checker types construction
        exactly as it types `datetime`'s: with `*args` any nonsense compiled.
        """
        if (
            tzinfo is not None
            and datetime(
                year, month, day, hour, minute, second, microsecond, tzinfo, fold=fold
            ).utcoffset()
        ):
            raise SnakeValueError(
                f"SnakeUtc is an instant in UTC and it was asked for with zone {tzinfo}. If you "
                f"wanted that moment expressed in UTC, SnakeUtc.of(datetime(..., tzinfo={tzinfo})): "
                f"converting in here would be changing your time without you having asked."
            )
        return super().__new__(
            cls, year, month, day, hour, minute, second, microsecond, UTC, fold=fold
        )

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        """The same instant in another zone, as a plain `datetime` — it is NO LONGER a `SnakeUtc`.

        This is the piece that keeps the type from being viral. `datetime.astimezone` rebuilds the
        SAME class, so without this a `SnakeUtc` in Madrid would try to exist and the constructor
        would reject it: any template or serialiser painting a date in local time would blow up. And
        the type changing is the CORRECT outcome: converted to Madrid it is no longer a UTC instant.
        """
        return self._plain().astimezone(tz)

    def replace(self, *args: Any, **kwargs: Any) -> datetime:  # type: ignore[override]
        """Like `datetime.replace`, but returning a plain `datetime` if the zone is changed.

        Same criterion as `astimezone`: relabelling the zone stops it being an instant in UTC, so it
        stops being a `SnakeUtc`. Leave the zone alone and it still is one.
        """
        requested_zone = kwargs.get("tzinfo", _SENTINEL)
        if requested_zone is _SENTINEL or requested_zone is UTC:
            return super().replace(*args, **kwargs)
        return self._plain().replace(*args, **kwargs)

    def _plain(self) -> datetime:
        """The same instant as a stdlib `datetime`, without this class's restrictions."""
        return datetime(
            self.year,
            self.month,
            self.day,
            self.hour,
            self.minute,
            self.second,
            self.microsecond,
            tzinfo=UTC,
        )

    @classmethod
    def now(cls, tz: object = None) -> SnakeUtc:
        """The current instant. The signature accepts `tz` for `datetime` compatibility and ignores
        it: a `SnakeUtc` is always UTC."""
        del tz
        return cls.of(datetime.now(UTC))

    @classmethod
    def of(cls, value: datetime) -> SnakeUtc:
        """Re-expresses in UTC a `datetime` that ALREADY has a zone. It does not move the instant.

        It rejects a naive one: with no zone there is no instant to re-express, it would have to be
        guessed where it is from.
        """
        if value.tzinfo is None or value.utcoffset() is None:
            raise SnakeValueError(
                f"{value!r} has no zone, so it identifies no instant: the same 14:30 are "
                f"different moments in Madrid and in Bogota. If you know which zone it is from, "
                f"SnakeUtc.from_zone(value, 'Europe/Madrid')."
            )
        in_utc = value.astimezone(UTC)
        return cls(
            in_utc.year,
            in_utc.month,
            in_utc.day,
            in_utc.hour,
            in_utc.minute,
            in_utc.second,
            in_utc.microsecond,
        )

    @classmethod
    def from_zone(cls, value: datetime, zone: str) -> SnakeUtc:
        """Places a LOCAL time in its zone and returns the instant in UTC.

            SnakeUtc.from_zone(datetime.fromisoformat(form["when"]), user.zone)

        It is the form's path. The zone is applied with its DAYLIGHT SAVING (`ZoneInfo`, not a fixed
        offset): the same 14:30 in Madrid are 12:30 UTC in June and 13:30 in January, and a fixed
        offset would be right half the year — the worst kind of bug, the one that only shows up for
        one season.
        """
        return cls.of(utc_from_zone(value, zone))

    @classmethod
    def parse(cls, text: str) -> SnakeUtc:
        """Reads an ISO-8601 WITH a zone. It is the direct path from JS.

        Text with no zone is REJECTED: it is what `<input type="datetime-local">` sends and it does
        not say where the time is from. Converting an offset here IS correct — you called `parse` to
        get the UTC — but inventing a zone that never came is not.
        """
        return cls.of(parse_utc(text))

    def to_zone(self, zone: str) -> datetime:
        """The same instant, expressed in another zone. For PAINTING it, not for storing it.

        Storing in UTC and showing in the reader's zone is the full cycle; this is its outbound half.
        """
        try:
            info = ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise SnakeValueError(
                f"{zone!r} is not a known time zone. IANA database names are expected, such as "
                f"'Europe/Madrid' or 'America/Bogota'."
            ) from error
        return self.astimezone(info)


_SENTINEL = object()
"""Marks "no `tzinfo` was passed" in `replace`, which `None` cannot tell apart (None IS valid)."""
