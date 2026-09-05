"""Adapts Python values a DBAPI driver cannot send, at EXECUTION time (not emission).

It has to live in execution: the emitters produce the original values the DDL needs as literals;
adapting earlier would write a `Decimal` as `'9.99'` inside a CHECK and cause phantom migrations.
Almost all of it is engine-agnostic: a single conversion, verified on all three.

The one exception is LISTS, and that is why `native_arrays` is a parameter and not an assumption.
Postgres has arrays and psycopg2 adapts them on its own; SQLite and MySQL do not have them, so the
list falls back to TEXT and travels as JSON. The one answering is the driver, which is the piece that
knows what its DBAPI understands. The answer used to be written in a comment in this module, the same
one for everybody, and that is why a list column only existed on Postgres.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from snakeorm.core.converters import to_db_for


def adapt_param(value: object, *, native_arrays: bool) -> object:
    """Converts a value into something any DBAPI driver knows how to send.

    It only acts on what some driver does not understand; the rest passes through untouched
    (converting "just in case" ends up converting twice). The conversion happens for every engine
    even when one of them does not need it: a single path, verified on all three by
    `test/integration/test_type_round_trip.py`.

    `native_arrays` is the ONLY point where the engine matters, and the driver answers it because it
    is the piece that knows what its DBAPI understands. This used to be an assumption hidden in a
    comment ("lists are left alone, psycopg2 adapts them"), which left the other two engines with no
    way to store a list. Now psycopg says yes and the others say no.
    """
    registered = to_db_for(value)
    if registered is not None:
        # A domain type declared with `register_converter`. It goes FIRST because a subclass of a
        # type the ORM already adapts has to be able to decide its own trip; otherwise this cascade
        # would treat it as its base and the declared `to_db` would never be called.
        return registered(value)
    if isinstance(value, list):
        # With native arrays, the list travels as-is and the driver adapts it. Without them it falls
        # back to TEXT, and JSON is the shape that knows how to come back: `_to_list` rebuilds it on
        # read.
        return value if native_arrays else json.dumps(value)
    if isinstance(value, dict):
        # `dict` -> JSON text; Postgres casts it to `jsonb` (and returns it parsed), SQLite stores
        # it as TEXT. `converter_for(dict)` closes the trip on both.
        return json.dumps(value)
    if isinstance(value, UUID):
        # Canonical text form, accepted by both engines. `_to_uuid` rebuilds it on read.
        return str(value)
    if isinstance(value, Decimal):
        # sqlite3 cannot send a `Decimal`. As TEXT (not `float`): a float would lose the exactness
        # that motivates declaring `Decimal`, silently and on one engine only.
        return str(value)
    if isinstance(value, timedelta):
        # `str(timedelta)` ("1 day, 2:30:00") is cast by Postgres to `interval` and stored by SQLite
        # as text; total seconds would demand a second representation for one engine alone.
        return str(value)
    if isinstance(value, (datetime, date, time)):
        # Python 3.12 removed sqlite3's date adapters. ISO 8601 is cast by Postgres without
        # ambiguity, time zone included.
        # `datetime` goes BEFORE `date`: it inherits from it, and the reverse order would truncate
        # the time.
        return value.isoformat()
    return value


def adapt_params(
    params: Sequence[object], *, native_arrays: bool, percent_formatting: bool
) -> tuple[object, ...] | None:
    """Adapts every param right before handing it to the DBAPI (the drivers call this).

    Returns a new tuple without mutating the one received: params can be reused (a retry), and
    adapting twice would turn a text into the text of a text.

    NEITHER flag has a default on purpose: a new driver has to answer, and answering wrong shows up
    immediately. With a default, the driver that forgot would inherit another library's behaviour.

    `native_arrays`: whether the engine has a real array type, or a list has to travel as text.

    `percent_formatting`: whether this DBAPI re-reads the SQL as a format template when given
    parameters. If it does, "no parameters" has to be spelled `None` — `()` still counts as being
    given some — and any statement carrying a literal `%` blows up before reaching the server. That
    is every DDL statement the runner emits, since DDL cannot be parametrised: a
    `CHECK (email LIKE '%mail%')`, a `DEFAULT '50% off'`, the body of a routine.

    Measured, and they do not agree, which is why this is a flag and not a blanket `or None`:

        psycopg 3   ()  -> ProgrammingError    None -> fine
        PyMySQL     ()  -> TypeError           None -> fine
        sqlite3     ()  -> fine                None -> ProgrammingError (it REFUSES None)

    This closes the EMPTY case only. A `%` alongside real parameters stays the caller's business,
    which is the same reason `MOD` is not in the capability catalogue.
    """
    adapted = tuple(adapt_param(value, native_arrays=native_arrays) for value in params)
    if not adapted and percent_formatting:
        return None
    return adapted
