"""Coercion of the driver's values to the declared python_type (the ORM is type-first: it guarantees the type).

DBAPI drivers do not always return the exact type (psycopg2 hands UUIDs back as str). The converters
are IDEMPOTENT, so they work for any driver without coupling to it. No converter for `int` on
purpose: `Decimal` -> `int` would truncate in silence.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import get_origin
from uuid import UUID

from snakeorm.core.converters import from_db_for, mark_builtin
from snakeorm.core.exceptions import SnakeValueError
from snakeorm.times import SnakeUtc


def _to_uuid(value: object) -> object:
    """psycopg2 returns UUID columns as `str`; other drivers already hand back a `UUID`."""
    return value if isinstance(value, UUID) else UUID(str(value))


def _to_float(value: object) -> object:
    """A Postgres `numeric` (AVG/SUM over numeric) arrives as a `Decimal`. It only converts
    numerics; the rest passes through untouched instead of blowing up."""
    if isinstance(value, float):
        return value
    if isinstance(value, (int, Decimal)):
        return float(value)
    return value


def _to_bool(value: object) -> object:
    """Converts to `bool` whatever the engine returns as 0/1 (SQLite stores integers; Postgres
    already hands back a `bool`, idempotent)."""
    return bool(value)


def _to_json(value: object) -> object:
    """Returns a `dict` out of whatever each engine hands over: Postgres already gives a `dict`
    (jsonb), SQLite gives TEXT and it gets parsed. Idempotent."""
    if isinstance(value, str):
        return json.loads(value)
    return value


def _to_decimal(value: object) -> object:
    """Rebuilds the `Decimal` out of whatever each engine returns (Postgres already gives a
    `Decimal`, SQLite gives text). It is parsed from the TEXT, never from a `float`: going through
    floating point would corrupt the precision (`1234.56` -> `1234.5599...`), exactly what a
    `Decimal` avoids.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (str, int)):
        return Decimal(value)
    return value


def _to_list(value: object) -> object:
    """Rebuilds the list out of whatever each engine returns.

    Postgres has arrays and psycopg2 already hands over a `list`; SQLite and MySQL do not have them,
    so the column is TEXT and what arrives is the JSON `adapt_param` wrote. Idempotent, and therein
    lies the trick that lets the converter registry be engine-agnostic while the SQL type is not:
    the same code swallows both shapes, so nobody has to ask which engine they are on.

    A text that is NOT JSON passes through untouched instead of blowing up: in Postgres a text column
    declared `list[str]` is an error of the model, and the error has to come out over there and not here.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _to_bytes(value: object) -> object:
    """A Postgres `bytea` arrives as a `memoryview`, not as `bytes`. The bug is invisible (it
    compares equal with `==`) until somebody does `hashlib.sha256(row.blob)`."""
    if isinstance(value, memoryview):
        return value.tobytes()
    return value


def _to_snake_utc(value: object) -> object:
    """Rebuilds a `SnakeUtc` out of whatever the driver returns.

    Without this the column would promise an instant in UTC and hand back a bare `datetime`: the
    declared type would stop being the type received, which is the central promise of the project.
    """
    read_back = _to_datetime(value)
    assert isinstance(
        read_back, datetime
    )  # `_to_datetime` normalises already or raises
    return (
        SnakeUtc.of(read_back)
        if read_back.tzinfo
        else SnakeUtc.of(read_back.replace(tzinfo=UTC))
    )


def _to_datetime(value: object) -> object:
    """Rebuilds the `datetime` from SQLite's ISO 8601 (Postgres already gives a `datetime`,
    idempotent; SQLite gives text ever since Python 3.12 withdrew its default converters)."""
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _to_date(value: object) -> object:
    """The same for `date`. A `datetime` is NOT truncated here: that would be inventing a conversion."""
    if isinstance(value, str):
        return date.fromisoformat(value)
    return value


def _to_time(value: object) -> object:
    """Rebuilds the `time` from what each engine hands back. Idempotent on Postgres.

    SQLite returns ISO text. **MySQL returns a `timedelta`**, and it is not a driver quirk: its
    `TIME` is a DURATION (-838:59:59 to 838:59:59), so PyMySQL is right to hand one over. A column
    declared `time` still has to come back as a `time`, which is this ORM's whole contract.

    A duration that does not fit in a day is not a clock reading, and it RAISES instead of wrapping
    round: `timedelta(hours=30)` quietly becoming `06:00` is a wrong answer wearing the face of a
    right one.
    """
    if isinstance(value, str):
        return time.fromisoformat(value)
    if isinstance(value, timedelta):
        if not timedelta(0) <= value < timedelta(days=1):
            raise SnakeValueError(
                f"a column declared `time` came back as {value!r}, which is not a time of day. "
                f"MySQL's TIME stores a duration and reaches from -838:59:59 to 838:59:59; declare "
                f"the column `timedelta` if that is what it holds."
            )
        hours, rest = divmod(value.seconds, 3600)
        minutes, seconds = divmod(rest, 60)
        return time(hours, minutes, seconds, value.microseconds)
    return value


_DURATION = re.compile(
    r"^(?:(?P<days>-?\d+) days?, )?(?P<hours>-?\d+):(?P<minutes>\d{2}):"
    r"(?P<seconds>\d{2})(?:\.(?P<micros>\d{1,6}))?$"
)


def _to_timedelta(value: object) -> object:
    """Rebuilds the `timedelta` from the text of `str(timedelta)` (Postgres already gives a
    `timedelta` via `interval`, idempotent; SQLite gives text). A text that does NOT match passes
    through untouched instead of blowing up.
    """
    if not isinstance(value, str):
        return value
    parts = _DURATION.match(value)
    if parts is None:
        return value
    days = int(parts["days"] or 0)
    hours = int(parts["hours"])
    sign = -1 if hours < 0 or (parts["hours"] or "").startswith("-") else 1
    return timedelta(
        days=days,
        hours=hours,
        minutes=sign * int(parts["minutes"]),
        seconds=sign * int(parts["seconds"]),
        microseconds=sign * int((parts["micros"] or "0").ljust(6, "0")),
    )


_CONVERTERS: dict[type, Callable[[object], object]] = {
    SnakeUtc: _to_snake_utc,
    UUID: _to_uuid,
    dict: _to_json,
    Decimal: _to_decimal,
    bytes: _to_bytes,
    datetime: _to_datetime,
    date: _to_date,
    time: _to_time,
    timedelta: _to_timedelta,
    float: _to_float,
    bool: _to_bool,
}


# They are declared at import time, and not listed by hand in `core/`: the source is this very
# registry, so adding an internal converter protects it on its own. `core/` cannot import from here
# (it would be a cycle between layers), so the direction is this one: the upper layer registers
# itself as it loads.
mark_builtin(_CONVERTERS.keys())


def _to_decimal_with_scale(scale: int) -> Callable[[object], object]:
    """Converter for a `Decimal` column that DECLARES a scale: it pads the value out to it.

    Adding zeros is safe; rounding is not, and this only ever adds. That is not a hope, it is
    guaranteed by the other half: `_guard_declared_limits` refuses on WRITE any value carrying more
    decimals than the scale, so nothing with more can be in the database to begin with. `quantize`
    here can only ever go the padding direction.

    It exists because the engines disagreed and the disagreement reached the screen. Postgres and
    MySQL apply the declared scale in storage and hand back `Decimal('1.00')`; SQLite keeps the text
    it was given and hands back `Decimal('1')`. The same NUMBER — `Decimal('1') == Decimal('1.00')`
    — so arithmetic never noticed, and `str()` did: one price printed `1` on one engine and `1.00`
    on another, out of one model.
    """
    exponent = Decimal(1).scaleb(-scale)

    def convert(value: object) -> object:
        """`Decimal('1')` -> `Decimal('1.00')`, from whatever each engine handed over."""
        rebuilt = _to_decimal(value)
        return rebuilt.quantize(exponent) if isinstance(rebuilt, Decimal) else rebuilt

    return convert


def converter_for(
    python_type: object, scale: int | None = None
) -> Callable[[object], object] | None:
    """The converter of a type, resolved ONCE, or `None` if the value passes through as is.

    It is resolved by TYPE (fixed per column), not per row, so as not to repeat the
    `issubclass`/lookup on the hot path; `None` avoids paying for a call per column with no conversion.

    Uniform CONTRACT: the converter does NOT handle the NULL — the caller guards it (`value is None`
    BEFORE invoking). A NULL is of another type (`_to_bool(None)` would give `False`, `_to_uuid(None)`
    would blow up); the inline guard in `hydrate` is free, and having NONE of them be None-safe stops
    one from handling it while another does not."""
    if python_type is Decimal and scale is not None:
        # The DECLARED scale travels with the column, so the value comes back carrying it whichever
        # engine stored it. See `_to_decimal_with_scale`: it only ever pads.
        return _to_decimal_with_scale(scale)
    if isinstance(python_type, type) and issubclass(python_type, Enum):
        # An enum is built by calling it, and it is idempotent with an already-built member.
        return _to_enum(python_type)
    # `python_type` is accepted as `object` because a column may declare a generic alias
    # (`list[str]`), which is NOT a class. Only `type`s can be in the registry.
    registered = from_db_for(python_type)
    if registered is not None:
        # A domain type declared with `register_converter`. It is consulted BEFORE the internal
        # registry so that a subclass of a handled type (of `str`, say) can declare its own way back;
        # without this it would come back as its base and the declared type would stop being the one
        # you receive, which is the silent failure this ORM does not commit.
        return registered
    if get_origin(python_type) is dict:
        # The twin of the `list` case below, and it was missing for the same reason it went
        # unnoticed: the compiler refused a parameterised dict before anybody could get here. With
        # that refusal lifted, no converter means the attribute declared `dict[str, object]` holds
        # the raw JSON string — and on an engine where the column is TEXT nothing complains at all.
        return _CONVERTERS.get(dict)
    if get_origin(python_type) is list:
        # This used to return `None`, and on Postgres it got away with it because psycopg2 already
        # hands over a list. On the engines without arrays the column is TEXT, so with no converter
        # the attribute declared `list[str]` would have held the raw JSON.
        return _to_list
    if not isinstance(python_type, type):
        return None
    return _CONVERTERS.get(python_type)


def _to_enum(enum_type: type[Enum]) -> Callable[[object], object]:
    """Converter for a concrete enum, closed over its class. It does NOT handle the NULL (the
    contract is in `converter_for`): the caller guards `value is None` beforehand."""

    def convert(value: object) -> object:
        """`Level("pro")` -> `Level.PRO`."""
        return enum_type(value)

    return convert


def coerce(value: object, python_type: object, scale: int | None = None) -> object:
    """Coerces `value` to the declared `python_type`. NULL and the types with no converter pass through untouched.

    A DELEGATION and not a second implementation, and that is the whole point. This is the door the
    write-back path comes through —the RETURNING of `add()`/`refresh()`, and `annotate`/prefetch—
    while `hydrate` comes through `converter_for`. Two doors into the same wardrobe: a value that
    went in one way and came out the other must not have changed TYPE on the trip. A subset here
    drifts, and what it drops is the user's own registrations: `from_db_for` — what
    `register_converter` fills — and the generic aliases. Measured,
    `converter_for(list[str])('["a","b"]')` gives `['a', 'b']` while a hand-rolled subset gave back
    the raw JSON string, so the same column read as a list through `all()` and as a `str` through
    `add()`.

    `python_type` is `object` and not `type` for the reason `converter_for` states: a column may
    declare a generic alias (`list[str]`), which is not a class.

    `scale` has to travel too, or the two doors disagree one parameter further down: without it the
    same column comes back `Decimal('1.00')` through `all()` and `Decimal('1')` through
    `add()`/`refresh()` — and `refresh()` is the sharp one, it takes an object that was already
    right and makes it worse. That stays invisible because `Decimal('1') == Decimal('1.00')` is
    True: every equality passes across the gap and arithmetic never notices. It shows up in
    `str()`, on a screen.
    """
    if value is None:
        return None
    converter = converter_for(python_type, scale)
    return converter(value) if converter is not None else value
