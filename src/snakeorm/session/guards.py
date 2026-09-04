"""The guards of a DECLARED limit: they are enforced in Python, before touching the database.

`snake_str(max_length=5)`, `snake_int(size=SMALLINT)` and `snake_decimal(precision=, scale=)` are
rules of the DOMAIN, not DDL ornaments. The ORM enforces them on write and does not delegate to the
engine, for two reasons: SQLite ignores the declared parameter — so in dev nothing would fail and in
prod it would — and when the engine does complain, it does so in its own jargon and halfway through
a bulk write.

They live here and not inside the session because they are not execution: they do not talk to the
driver, know nothing of transactions and do not depend on whether anyone awaited. The SYNCHRONOUS
session had them inside it, so the asynchronous one depended on it in order not to duplicate them —
one layer importing its sibling to ask it for something that belongs to neither of them.

None of them truncates or rounds. A `max_length` that cuts the string turns a rule into silent data
loss; the ORM shouts and whoever is writing decides.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from snakeorm.core.exceptions import (
    SnakeEmitError,
    SnakeUnsupportedFeature,
    SnakeValueError,
)
from snakeorm.dialects.base import SnakeDialect
from snakeorm.dialects.capabilities import Cap, Nope
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIntSize,
    SnakeTableInfo,
)
from snakeorm.fields import MISSING
from snakeorm.times import SnakeUtc


# Range of a signed integer per declared width. It is what Postgres enforces and SQLite does not:
# SQLite collapses every integer into its 64-bit INTEGER, so an overflowed SMALLINT gets in.
_INT_RANGES: dict[SnakeIntSize, tuple[int, int]] = {
    SnakeIntSize.SMALLINT: (-(2**15), 2**15 - 1),
    SnakeIntSize.INTEGER: (-(2**31), 2**31 - 1),
    SnakeIntSize.BIGINT: (-(2**63), 2**63 - 1),
}


def _guard_declared_limits(table: SnakeTableInfo, values: dict[str, object]) -> None:
    """Rejects a value that falls outside its column's DECLARED limit, before touching the database.

    A declared knob (`scale`, `max_length`, `int_size`) is a rule of the domain. If the ORM only
    writes it into the DDL, the ENGINE is what enforces it — and then it means different things
    depending on where you run: Postgres rejects (`value too long`, `smallint out of range`) and
    SQLite accepts, because it ignores the VARCHAR's length and collapses the integers. Checking it
    here makes it hold on BOTH.

    This is no detail: the SQLite dialect exists so one can work without a server, so without this
    the suite comes out green in development and the deployment to Postgres blows up.

    It SHOUTS, it never trims: truncating the text or rounding the number would be converting behind
    the developer's back. The value gets fixed by whoever wrote it.
    """
    for column in table.columns:
        value = values.get(column.name)
        if value is None or column.name not in values:
            continue  # a NULL is not measured: nullability is decided by the annotation, not by these limits
        _guard_scale(table, column, value)
        _guard_length(table, column, value)
        _guard_int_range(table, column, value)
        _guard_timezone(table, column, value)


def _guard_scale(table: SnakeTableInfo, column: SnakeColumnInfo, value: object) -> None:
    """Decimal places of a `Decimal` against the declared `scale`.

    NaN/Inf (a non-numeric exponent) pass through so the engine rejects them, with a more specific
    message than could be given here.
    """
    if column.scale is None or not isinstance(value, Decimal):
        return
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > column.scale:
        raise SnakeValueError(
            f"{table.name}.{column.name} declares scale={column.scale} but an attempt was made to "
            f"write {value}, with {-exponent} decimal places. Quantize it yourself "
            f"(value.quantize(...)) before saving it: the ORM does not round in silence."
        )


def _guard_length(
    table: SnakeTableInfo, column: SnakeColumnInfo, value: object
) -> None:
    """Length of a text against the declared `max_length`. The limit is INCLUSIVE."""
    if column.max_length is None or not isinstance(value, str):
        return
    if len(value) > column.max_length:
        raise SnakeValueError(
            f"{table.name}.{column.name} declares max_length={column.max_length} but an attempt was "
            f"made to write a text of {len(value)} characters. Trim it yourself before saving it: "
            f"the ORM does not truncate in silence."
        )


def _guard_timezone(
    table: SnakeTableInfo, column: SnakeColumnInfo, value: object
) -> None:
    """Demands that a `datetime` say the same thing as its column about carrying a zone, and be UTC.

    It is the runtime safety net: the type already prevents it in the editor (`SnakeUtc` cannot be
    built outside UTC), but whoever skips the checker also deserves a clear message.

    On a `SnakeUtc` column (`TIMESTAMPTZ`) ONLY UTC is admitted. The column stores the INSTANT, not
    the offset: were `14:30+02:00` accepted, Postgres would return `12:30+00:00` and SQLite
    `14:30+02:00`, that is, `.hour` would be 12 or 14 depending on the engine.

    On a `datetime` column (`TIMESTAMP`, wall-clock time) the opposite is rejected: discarding a
    `tzinfo` really does destroy the instant, silently and only sometimes.
    """
    if not isinstance(value, datetime):
        return
    offset = value.utcoffset()
    if column.python_type is SnakeUtc:
        if offset is None:
            raise SnakeValueError(
                f"{table.name}.{column.name} stores an instant (with a zone) but {value!r} does not "
                f"carry one, so it identifies none: the same 14:30 is a different moment in "
                f"Madrid and in Bogotá. Place it with utc_from_zone(value, 'Europe/Madrid') or "
                f"use SnakeUtc.now(); if it really is a wall-clock time, declare it with "
                f"snake_datetime() and SnakeColumn[datetime]."
            )
        if offset:
            raise SnakeValueError(
                f"{table.name}.{column.name} only accepts UTC and {value!r} comes with offset "
                f"{offset}. The column stores the INSTANT, not the offset: Postgres would give "
                f"it back to you in UTC and SQLite with the original offset, so `.hour` would "
                f"change from engine to engine. Convert it yourself with to_utc(value): the ORM "
                f"does not change zone in silence."
            )
        return
    if column.python_type is not datetime:
        return
    if offset is not None:
        raise SnakeValueError(
            f"{table.name}.{column.name} is declared SnakeColumn[datetime], that is, a WALL-CLOCK "
            f"TIME, and {value!r} carries a zone. Saving it would throw away the tzinfo and with "
            f"it the instant, silently. If you meant to store the instant, declare the column "
            f"SnakeColumn[SnakeUtc]; if it really is a wall-clock time, pass a datetime without "
            f"a zone."
        )


def _guard_int_range(
    table: SnakeTableInfo, column: SnakeColumnInfo, value: object
) -> None:
    """Value of an integer against the range of its declared width.

    It dispatches on the column's DECLARED TYPE, not on the value's: in Python `bool` is a subclass
    of `int`, so looking at the value would measure the width of a boolean column.
    """
    if column.python_type is not int or not isinstance(value, int):
        return
    minimum, maximum = _INT_RANGES[column.int_size]
    if not minimum <= value <= maximum:
        raise SnakeValueError(
            f"{table.name}.{column.name} declares {column.int_size.name} (from {minimum} to {maximum}) "
            f"but an attempt was made to write {value}. Postgres would reject it and SQLite would "
            f"accept it: the ORM rejects it on both so that your model means the same on either."
        )


def _guard_required_values(
    table: SnakeTableInfo, raw_values: Mapping[str, object]
) -> None:
    """Shouts if a MANDATORY column arrives carrying the `MISSING` sentinel instead of a value.

    Leaving a `MISSING` out of the INSERT is the right thing almost always — an autoincrementing PK,
    a column with a default, one the server fills in — and that is why the silence got mistaken for
    the norm. What is separated out here is the case where omitting is exactly the opposite: NOT
    NULL, with no default of any kind and no autoincrement. There the `MISSING` does not mean "let
    the database put it in", it means nobody put it in, and taking it out of the INSERT turns a
    program error into an engine problem.

    Where a `MISSING` sneaking in as a value comes from: on an engine without `RETURNING`, an
    `add_all()` leaves the PKs unfilled, and that id which never came back ends up being the foreign
    key of the next row. Four steps in silence, and an `INSERT INTO bridge () VALUES ()` at the end
    that points at none of them.
    """
    for column in table.columns:
        if raw_values.get(column.name, None) is not MISSING:
            continue
        if _fills_itself(column):
            continue
        raise SnakeValueError(
            f"'{table.name}.{column.name}' is mandatory (NOT NULL, without a default and without "
            f"autoincrement) and an attempt was made to write it without a value. It usually means "
            f"the value comes from another row whose id never came back: on an engine without "
            f"RETURNING, `add_all()` does not fill in autoincrementing keys, so use `add()` for "
            f"the rows whose id you need afterwards."
        )


def _fills_itself(column: SnakeColumnInfo) -> bool:
    """Whether it is legitimate for the column to arrive with no value: somebody puts it in for it.

    Four ways for that to be so, and all four count: it accepts NULL, the database generates it, it
    carries a declared default, or the server puts it in. Missing one would turn this guard into a
    false positive over perfectly correct models, which is how a guard dies.
    """
    return (
        column.nullable
        or column.autoincrement
        or column.has_default
        or column.default_factory is not None
        or column.has_server_default
    )


def guard_uniform_bulk_columns(rows: list[dict[str, object]], model_name: str) -> None:
    """Every instance of an `add_all` must carry the SAME columns. Refuses the batch if not.

    The second half of a requirement stated three lines above the caller: `add_all` demands a single
    MODEL. One model does not mean one shape — a column with a server default stays out of
    `__init__`, so two instances of the same class can legitimately end up with different sets of
    assigned values, and rows with different columns cannot share one multi-row INSERT. Without this
    guard the POSITION of an element in the list decided between a loud error and a silent loss of
    data: an empty first row emitted `DEFAULT VALUES` for EVERY instance, while the same two rows
    the other way round raised. Same batch, opposite outcomes, decided by the order they were
    appended in.

    Refusing rather than splitting the batch into groups is the same answer the emitter already
    gives, and it is the one this ORM's doctrine asks for: what cannot be done as asked gets said,
    not quietly turned into something else. Grouping would also hand back rows in an order the
    caller did not choose, which `add_all` promises it does not do.
    """
    if len(rows) < 2:
        return
    shapes = {tuple(sorted(row)) for row in rows}
    if len(shapes) == 1:
        return
    spellings = sorted(
        ", ".join(shape) if shape else "(no columns)" for shape in shapes
    )
    raise SnakeEmitError(
        f"Every row of a bulk INSERT must have the same columns, and these {model_name} "
        f"instances do not: {' / '.join(spellings)}. One model does not mean one shape — a column "
        f"with a server default stays out of the constructor, so assigning it on some instances "
        f"and not others splits the batch. Either assign it on all of them or on none, or call "
        f"add() per instance."
    )


def guard_can_set_isolation(dialect: SnakeDialect) -> None:
    """Refuses `SET TRANSACTION ISOLATION LEVEL` on an engine that declares it cannot.

    It lives here, in one piece called by BOTH colours, and that is the whole point of moving it.
    The synchronous session asked the catalogue and the asynchronous one handed the statement
    straight to the driver, so SQLite answered `near "SET": syntax error` — the exact failure the
    synchronous docstring says the check exists to prevent, reproduced in the other colour because
    the fix had only been applied to one.

    A session emitting engine SQL without asking is also what the dialect seam exists to stop, so
    the drift was not only about wording: half the ORM was reaching past the seam.
    """
    support = dialect.capabilities.support_for(Cap.SET_ISOLATION)
    if isinstance(support, Nope):
        raise SnakeUnsupportedFeature(
            f"{type(dialect).__name__} cannot set the isolation level: {support.reason}."
        )
