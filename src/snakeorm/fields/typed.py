"""Field specifiers BY TYPE FAMILY: `snake_int`, `snake_str`, `snake_decimal`, `snake_json`.

Each one carries ONLY the SQL parameters of its family, plus the type-agnostic ones (key,
uniqueness, index, name, comment, defaults). That way the checker stops offering `max_length=` on a
`SnakeColumn[int]` or `json_storage=` on a `SnakeColumn[datetime]`: the illegal state cannot be
written, which is the thesis of the project, instead of merely shouting at compile time.

It is not a new pattern: `snake_enum` and `snake_auto` already were this. These four finish it.
`snake_column()` stays for the types WITHOUT parameters (`bool`, `date`, `UUID`, `bytes`,
`timedelta`...), now without a single type-specific knob.

The three overloads per specifier repeat the signature. It is the SAME duplication as the one in
`field_specifiers`: PEP 681 and `@overload` demand literal signatures, so the language imposes it.
What can be done is keep it from drifting, and `test/fields/test_typed_specifiers.py` takes care
of that.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time
from decimal import Decimal
from typing import Any, Literal, overload

from snakeorm.fields.column import MISSING, SnakeColumn
from snakeorm.metadata import (
    SnakeDateTimeParams,
    SnakeDecimalParams,
    SnakeFloatParams,
    SnakeIntParams,
    SnakeIntSize,
    SnakeJsonParams,
    SnakeJsonStorage,
    SnakeServerDefault,
    SnakeStrParams,
    SnakeTimeParams,
)


@overload
def snake_int(
    *,
    server_default: SnakeServerDefault,
    server_default_sql: str | None = ...,
    size: SnakeIntSize = ...,
    default: int | None = ...,
    default_factory: Callable[[], int] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_int(
    *,
    server_default_sql: str,
    server_default: SnakeServerDefault | None = ...,
    size: SnakeIntSize = ...,
    default: int | None = ...,
    default_factory: Callable[[], int] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_int(
    *,
    size: SnakeIntSize = ...,
    default: int | None = ...,
    default_factory: Callable[[], int] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
) -> Any: ...
def snake_int(
    *,
    size: SnakeIntSize = SnakeIntSize.BIGINT,
    default: object = MISSING,
    default_factory: Callable[[], int] | None = None,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    name: str | None = None,
    db_comment: str | None = None,
    server_default: SnakeServerDefault | None = None,
    server_default_sql: str | None = None,
    init: Literal[False] = False,
) -> Any:
    """Declare an integer column, choosing its WIDTH in the database.

        stock: SnakeColumn[int] = snake_int(size=SnakeIntSize.SMALLINT)

    `size` is the only parameter specific to this family: it picks SMALLINT/INTEGER/BIGINT. The
    default is `BIGINT`, the widest of the supported engines, so that Python's unbounded `int`
    means the same thing in Postgres and in SQLite. For an autoincrementing PK use `snake_auto()`,
    which on top of that excludes the column from the constructor.
    """
    del init  # typing signal only; the runtime excludes via `server_default`
    return SnakeColumn(
        type_params=SnakeIntParams(size=size),
        declared_by="snake_int",
        default=default,
        default_factory=default_factory,
        primary_key=primary_key,
        unique=unique,
        index=index,
        name=name,
        db_comment=db_comment,
        server_default=server_default,
        server_default_sql=server_default_sql,
    )


@overload
def snake_str(
    *,
    server_default: SnakeServerDefault,
    server_default_sql: str | None = ...,
    max_length: int | None = ...,
    fixed: bool = ...,
    default: str | None = ...,
    default_factory: Callable[[], str] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_str(
    *,
    server_default_sql: str,
    server_default: SnakeServerDefault | None = ...,
    max_length: int | None = ...,
    fixed: bool = ...,
    default: str | None = ...,
    default_factory: Callable[[], str] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_str(
    *,
    max_length: int | None = ...,
    fixed: bool = ...,
    default: str | None = ...,
    default_factory: Callable[[], str] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
) -> Any: ...
def snake_str(
    *,
    max_length: int | None = None,
    fixed: bool = False,
    default: object = MISSING,
    default_factory: Callable[[], str] | None = None,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    name: str | None = None,
    db_comment: str | None = None,
    server_default: SnakeServerDefault | None = None,
    server_default_sql: str | None = None,
    init: Literal[False] = False,
) -> Any:
    """Declare a text column, optionally with a maximum length.

        name: SnakeColumn[str] = snake_str(max_length=50)

    Without `max_length` the column is TEXT. With it Postgres emits `VARCHAR(n)`, which is not
    faster than TEXT: it STATES a domain rule and the database enforces it. SQLite ignores it.

    With `fixed=True` the column is `CHAR(n)`, of FIXED length. It is not a stricter VARCHAR: it
    pads with spaces up to `n` and compares ignoring that padding, which is exactly what someone
    storing country codes or a hash of known length wants. It demands `max_length`: a CHAR without
    a length is CHAR(1) in SQL, and guessing that 1 would be deciding for whoever did not decide.
    """
    del init  # typing signal only; the runtime excludes via `server_default`
    return SnakeColumn(
        type_params=SnakeStrParams(max_length=max_length, fixed=fixed),
        declared_by="snake_str",
        default=default,
        default_factory=default_factory,
        primary_key=primary_key,
        unique=unique,
        index=index,
        name=name,
        db_comment=db_comment,
        server_default=server_default,
        server_default_sql=server_default_sql,
    )


@overload
def snake_decimal(
    *,
    server_default: SnakeServerDefault,
    precision: int,
    scale: int | None = ...,
    server_default_sql: str | None = ...,
    default: Decimal | None = ...,
    default_factory: Callable[[], Decimal] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_decimal(
    *,
    server_default_sql: str,
    precision: int,
    scale: int | None = ...,
    server_default: SnakeServerDefault | None = ...,
    default: Decimal | None = ...,
    default_factory: Callable[[], Decimal] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_decimal(
    *,
    precision: int,
    scale: int | None = ...,
    default: Decimal | None = ...,
    default_factory: Callable[[], Decimal] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
) -> Any: ...
def snake_decimal(
    *,
    precision: int,
    scale: int | None = None,
    default: object = MISSING,
    default_factory: Callable[[], Decimal] | None = None,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    name: str | None = None,
    db_comment: str | None = None,
    server_default: SnakeServerDefault | None = None,
    server_default_sql: str | None = None,
    init: Literal[False] = False,
) -> Any:
    """Declare a NUMERIC column with its precision and scale.

        price: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)

    `precision` is MANDATORY, and on purpose: a `NUMERIC` without precision accepts any number of
    digits, so the rounding of money stops being declared and starts depending on whatever comes
    in. Whoever wants that behaviour asks for it explicitly with `snake_column()`.
    """
    del init  # typing signal only; the runtime excludes via `server_default`
    return SnakeColumn(
        type_params=SnakeDecimalParams(precision=precision, scale=scale),
        declared_by="snake_decimal",
        default=default,
        default_factory=default_factory,
        primary_key=primary_key,
        unique=unique,
        index=index,
        name=name,
        db_comment=db_comment,
        server_default=server_default,
        server_default_sql=server_default_sql,
    )


@overload
def snake_json(
    *,
    server_default: SnakeServerDefault,
    server_default_sql: str | None = ...,
    storage: SnakeJsonStorage = ...,
    default_factory: Callable[[], dict[str, Any]] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_json(
    *,
    server_default_sql: str,
    server_default: SnakeServerDefault | None = ...,
    storage: SnakeJsonStorage = ...,
    default_factory: Callable[[], dict[str, Any]] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_json(
    *,
    storage: SnakeJsonStorage = ...,
    default_factory: Callable[[], dict[str, Any]] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
) -> Any: ...
def snake_json(
    *,
    storage: SnakeJsonStorage = SnakeJsonStorage.JSONB,
    default_factory: Callable[[], dict[str, Any]] | None = None,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    name: str | None = None,
    db_comment: str | None = None,
    server_default: SnakeServerDefault | None = None,
    server_default_sql: str | None = None,
    init: Literal[False] = False,
) -> Any:
    """Declare a JSON column, choosing how the engine backs it.

        meta: SnakeColumn[dict[str, object]] = snake_json(storage=SnakeJsonStorage.JSON)

    `JSONB` (the default) normalises and indexes; `JSON` preserves the exact text that came in.
    SQLite collapses both to TEXT.

    There is no `default`: a mutable literal shared between instances is the classic Python
    defaults bug, and in the DDL a `DEFAULT '{}'` is rarely what you want. For an initial value use
    `default_factory=dict`, which builds a fresh one per instance and never touches the DDL.
    """
    del init  # typing signal only; the runtime excludes via `server_default`
    return SnakeColumn(
        type_params=SnakeJsonParams(storage=storage),
        declared_by="snake_json",
        default_factory=default_factory,
        primary_key=primary_key,
        unique=unique,
        index=index,
        name=name,
        db_comment=db_comment,
        server_default=server_default,
        server_default_sql=server_default_sql,
    )


def _date_column(
    *,
    declared_by: str,
    tz: bool,
    precision: int | None,
    default_factory: Callable[[], datetime] | None,
    primary_key: bool,
    unique: bool,
    index: bool,
    name: str | None,
    db_comment: str | None,
    server_default: SnakeServerDefault | None,
    server_default_sql: str | None,
) -> Any:
    """Common body of the two date declarators. The only thing that changes is `tz`."""
    return SnakeColumn(
        type_params=SnakeDateTimeParams(tz=tz, precision=precision),
        declared_by=declared_by,
        default_factory=default_factory,
        primary_key=primary_key,
        unique=unique,
        index=index,
        name=name,
        db_comment=db_comment,
        server_default=server_default,
        server_default_sql=server_default_sql,
    )


@overload
def snake_datetimetz(
    *,
    server_default: SnakeServerDefault,
    server_default_sql: str | None = ...,
    precision: int | None = ...,
    default_factory: Callable[[], datetime] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_datetimetz(
    *,
    server_default_sql: str,
    server_default: SnakeServerDefault | None = ...,
    precision: int | None = ...,
    default_factory: Callable[[], datetime] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_datetimetz(
    *,
    precision: int | None = ...,
    default_factory: Callable[[], datetime] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
) -> Any: ...
def snake_datetimetz(
    *,
    precision: int | None = None,
    default_factory: Callable[[], datetime] | None = None,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    name: str | None = None,
    db_comment: str | None = None,
    server_default: SnakeServerDefault | None = None,
    server_default_sql: str | None = None,
    init: Literal[False] = False,
) -> Any:
    """Declare a `TIMESTAMPTZ` column: it stores an INSTANT, with a zone.

        occurred_at: SnakeColumn[SnakeUtc] = snake_datetimetz()

    The annotation has to be `SnakeUtc`, and the compiler demands it. Each one covers what the
    other cannot: the declarator says which COLUMN gets created, whereas `SnakeUtc` says which
    VALUE is admitted and the checker enforces that before anything runs. The guard ties the two
    together, so the redundancy cannot lie. Same treatment as `snake_enum(Status)`.

    `TIMESTAMPTZ` stores the moment, NOT the offset it was written with: that is why it only
    admits UTC, and to get there you have `SnakeUtc.parse()`, `.from_zone()`, `.of()` and
    `.now()`.

    `precision` is the fractional-second digits: `0` whole seconds, `3` milliseconds, `6` the
    Postgres default (exactly the resolution of Python's `datetime`). SQLite ignores it.

    There is no literal `default`: a fixed date in the DDL is almost never what you want. For
    "now" use `server_default=SnakeServerDefault.NOW` or `default_factory=SnakeUtc.now`."""
    del init  # typing signal only; the runtime excludes via `server_default`
    return _date_column(
        declared_by="snake_datetimetz",
        tz=True,
        precision=precision,
        default_factory=default_factory,
        primary_key=primary_key,
        unique=unique,
        index=index,
        name=name,
        db_comment=db_comment,
        server_default=server_default,
        server_default_sql=server_default_sql,
    )


@overload
def snake_datetime(
    *,
    server_default: SnakeServerDefault,
    server_default_sql: str | None = ...,
    precision: int | None = ...,
    default_factory: Callable[[], datetime] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_datetime(
    *,
    server_default_sql: str,
    server_default: SnakeServerDefault | None = ...,
    precision: int | None = ...,
    default_factory: Callable[[], datetime] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_datetime(
    *,
    precision: int | None = ...,
    default_factory: Callable[[], datetime] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
) -> Any: ...
def snake_datetime(
    *,
    precision: int | None = None,
    default_factory: Callable[[], datetime] | None = None,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    name: str | None = None,
    db_comment: str | None = None,
    server_default: SnakeServerDefault | None = None,
    server_default_sql: str | None = None,
    init: Literal[False] = False,
) -> Any:
    """Declare a `TIMESTAMP` column: it stores a WALL-CLOCK TIME, without a zone.

        opens_at: SnakeColumn[datetime] = snake_datetime()

    A wall-clock time identifies no instant until somebody says which zone it belongs to: it is
    what you want for opening hours or a local holiday, and what you do NOT want for a
    `created_at`. That is what `snake_datetimetz()` is for.

    The annotation has to be plain `datetime`, and the compiler demands it: a `SnakeUtc` here
    would lose its `tzinfo` on save, silently.

    `precision` is the fractional-second digits. SQLite ignores it.

    There is no literal `default`: a fixed date in the DDL is almost never what you want."""
    del init  # typing signal only; the runtime excludes via `server_default`
    return _date_column(
        declared_by="snake_datetime",
        tz=False,
        precision=precision,
        default_factory=default_factory,
        primary_key=primary_key,
        unique=unique,
        index=index,
        name=name,
        db_comment=db_comment,
        server_default=server_default,
        server_default_sql=server_default_sql,
    )


@overload
def snake_float(
    *,
    server_default: SnakeServerDefault,
    server_default_sql: str | None = ...,
    size: int = ...,
    default: float | None = ...,
    default_factory: Callable[[], float] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_float(
    *,
    server_default_sql: str,
    server_default: SnakeServerDefault | None = ...,
    size: int = ...,
    default: float | None = ...,
    default_factory: Callable[[], float] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
    init: Literal[False] = False,
) -> Any: ...
@overload
def snake_float(
    *,
    size: int = ...,
    default: float | None = ...,
    default_factory: Callable[[], float] | None = ...,
    primary_key: bool = ...,
    unique: bool = ...,
    index: bool = ...,
    name: str | None = ...,
    db_comment: str | None = ...,
) -> Any: ...
def snake_float(
    *,
    size: int = 8,
    default: object = MISSING,
    default_factory: Callable[[], float] | None = None,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    name: str | None = None,
    db_comment: str | None = None,
    server_default: SnakeServerDefault | None = None,
    server_default_sql: str | None = None,
    init: Literal[False] = False,
) -> Any:
    """Declare a floating-point column, optionally 4 bytes instead of 8.

        price: SnakeColumn[float] = snake_float(size=4)

    The default is 8 —double precision, which is what a Python `float` IS— and it does not change:
    lowering it would make an already written model silently lose precision on upgrade. With
    `size=4` the column takes half the space, which on a table of millions of rows is the
    difference you are after.

    SQLite emits `REAL` for both: it has a single floating-point class, and its degraded capability
    says so, instead of faking a precision the engine does not deliver.
    """
    del init  # typing signal only; the runtime excludes via `server_default`
    return SnakeColumn(
        type_params=SnakeFloatParams(size=size),
        declared_by="snake_float",
        default=default,
        default_factory=default_factory,
        primary_key=primary_key,
        unique=unique,
        index=index,
        name=name,
        db_comment=db_comment,
        server_default=server_default,
        server_default_sql=server_default_sql,
    )


def _time_column(with_timezone: bool, kwargs: dict[str, object]) -> Any:
    """The shared body of the two time declarators. Just one, so they cannot diverge.

    Drift between two sibling declarators already happened on this branch with the dates: the body
    got copied, one of them was touched and the other stayed behind.
    """
    return SnakeColumn(
        type_params=SnakeTimeParams(with_timezone=with_timezone),
        **kwargs,  # type: ignore[arg-type]
    )


def snake_time(
    *,
    default: object = MISSING,
    default_factory: Callable[[], time] | None = None,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    name: str | None = None,
    db_comment: str | None = None,
    server_default: SnakeServerDefault | None = None,
    server_default_sql: str | None = None,
) -> Any:
    """Declare a time of day WITHOUT a zone (`TIME`).

        opens_at: SnakeColumn[time] = snake_time()

    It is the time on a wall clock: nine o'clock is nine o'clock wherever it gets read. If what
    you are storing is a moment of the day tied to an offset, use `snake_timetz()`.
    """
    return _time_column(
        False,
        {
            "default": default,
            "default_factory": default_factory,
            "primary_key": primary_key,
            "unique": unique,
            "index": index,
            "name": name,
            "db_comment": db_comment,
            "server_default": server_default,
            "server_default_sql": server_default_sql,
        },
    )


def snake_timetz(
    *,
    default: object = MISSING,
    default_factory: Callable[[], time] | None = None,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    name: str | None = None,
    db_comment: str | None = None,
    server_default: SnakeServerDefault | None = None,
    server_default_sql: str | None = None,
) -> Any:
    """Declare a time of day WITH a zone (`TIMETZ`).

        opens_at: SnakeColumn[time] = snake_timetz()

    Two declarators and not a knob, same as with the dates: the column SAYS which type it creates,
    instead of it depending on whether the first value that arrived carried an offset. A plain
    `TIME` throws the zone away, and an opening hour seen from somewhere else stops meaning the
    same thing.

    Where the engine has no `TIMETZ` (MySQL, SQLite) the column falls back to TEXT and keeps the
    offset inside the ISO text — which is more than a native `TIME` would keep.
    """
    return _time_column(
        True,
        {
            "default": default,
            "default_factory": default_factory,
            "primary_key": primary_key,
            "unique": unique,
            "index": index,
            "name": name,
            "db_comment": db_comment,
            "server_default": server_default,
            "server_default_sql": server_default_sql,
        },
    )
