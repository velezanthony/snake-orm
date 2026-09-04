"""EVERY supported type, written and read back, on EVERY engine. The matrix that was missing.

This file is born of a hole that was hard to find and should not have cost anything at all: `dict`
(JSON) columns **did not work on any engine**. The DDL emitted an impeccable `JSONB`, the task was
marked as finished, the documentation promised it... and the first `INSERT` blew up with `can't
adapt type 'dict'`. It had never worked.

How did it go unnoticed with 1351 tests? Because the test that "covered" JSON was this one:

    assert dialect.map_type(dict) == "JSONB"

Comparing a string. The repository itself has the lesson written down, in
`test/migration/test_render_completeness.py`: *"a test that measures the source code measures the
source code; to know whether something works you have to call it"*. It was written on the wall and
ten metres away there was a test that called nothing.

So this does not test types: it tests the project's CENTRAL CONTRACT —*the declared type is the type
you get*— by running it. It writes a value, reads it back, and demands that it come back with its
type and its value. It is the only form of check that cannot be satisfied without the functionality
existing.

And it goes as a matrix per ENGINE because the other lesson of this branch is that testing one
engine out of two is testing half: two catastrophic bugs that only existed on SQLite came out just
today.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import IntEnum, StrEnum
from uuid import UUID, uuid4

import pytest

from test.conftest import NO_MYSQL_REASON, NO_SERVER_REASON

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    PsycopgDriver,
    PyMySQLDriver,
    SQLiteDialect,
    SQLiteDriver,
    SnakeColumn,
    SnakeDialect,
    SnakeDriver,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SnakeUtc,
    snake_auto,
    snake_column,
    snake_datetime,
    snake_datetimetz,
    snake_decimal,
    snake_enum,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.core.config import dsn_from_env
from test.scenarios.engines import mysql_kwargs
from snakeorm.migration import emit_create_table, emit_drop_table


class State(StrEnum):
    """Enumerado de text."""

    ACTIVE = "active"
    CLOSED = "closed"


class Level(IntEnum):
    """Enumerado numérico."""

    BAJO = 1
    ALTO = 9


@snake_model(table="rt_todos")
class AllTypes(SnakeModel):
    """One column for every type the ORM claims to support. Not one less.

    Having them ALL in a single model is deliberate: one table per type would allow forgetting to
    add the next one, and a type without a line in this class is an untested type. Here the absence
    shows.
    """

    id: SnakeColumn[int] = snake_auto()
    text: SnakeColumn[str] = snake_str()
    entero: SnakeColumn[int] = snake_int()
    booleano: SnakeColumn[bool] = snake_column()
    real: SnakeColumn[float] = snake_column()
    exact_amount: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)
    instant: SnakeColumn[SnakeUtc] = snake_datetimetz()
    pared: SnakeColumn[datetime] = snake_datetime()
    day: SnakeColumn[date] = snake_column()
    public_id: SnakeColumn[UUID] = snake_column()
    crudo: SnakeColumn[bytes] = snake_column()
    clock_time: SnakeColumn[time] = snake_column()
    duracion: SnakeColumn[timedelta] = snake_column()
    document: SnakeColumn[dict] = snake_column()
    status: SnakeColumn[State] = snake_enum(State)
    level: SnakeColumn[Level] = snake_enum(Level)
    opcional: SnakeColumn[str | None] = snake_str()


_UUID = uuid4()
_INSTANT = SnakeUtc(2026, 3, 14, 15, 9, 26)
# WALL clock time: a plain `datetime` identifies no instant at all, and it is what
# a TIMESTAMP without a zone stores (opening hours, a local holiday).
_WALL = datetime(2026, 3, 14, 15, 9, 26)

# What gets written, and what has to come back. They are the SAME value on purpose: if two
# different columns ever have to be written here, that type does not meet the contract and it has
# to be said in `docs/users/reference/limits.md`, not made up in the test.
_EXPECTED: dict[str, object] = {
    "text": "hola",
    "entero": 42,
    "booleano": True,
    "real": 2.5,
    "exact_amount": Decimal("1234.56"),
    "instant": _INSTANT,
    "pared": _WALL,
    "day": date(2026, 3, 14),
    "public_id": _UUID,
    "crudo": b"\x00\x01\xff",
    "clock_time": time(15, 9, 26),
    "duracion": timedelta(days=1, hours=2, minutes=30),
    "document": {"key": "value", "nested": {"list": [1, 2, 3]}},
    "status": State.CLOSED,
    "level": Level.ALTO,
    "opcional": None,
}


_SESSION: list[SnakeSession] = [None]  # type: ignore[list-item]
"""The session of the fixture in progress, so that the FILTERING test reuses its connection.

With `:memory:` there is no alternative: another connection is another empty database."""


@snake_model(table="rt_soloid")
class _SoloId(SnakeModel):
    """Only an autoincrement PK: a legitimate schema that could not be inserted."""

    id: SnakeColumn[int] = snake_auto()


def _connector(engine: str) -> tuple[SnakeDriver, SnakeDialect]:
    """Driver and dialect of the requested engine. With Postgres absent, it skips.

    It returns the two Protocols, not `object`: in a file whose thesis is that the declared type is
    the type you get, writing the harness with `object` and a row of `type: ignore` would be
    preaching one thing and doing another.
    """
    if engine == "sqlite":
        return SQLiteDriver.connect(":memory:"), SQLiteDialect()

    if engine == "mysql":
        import pymysql

        try:
            return (
                PyMySQLDriver.connect(**mysql_kwargs()),  # type: ignore[arg-type]
                MySQLDialect(),
            )
        except (
            pymysql.err.OperationalError
        ) as error:  # pragma: no cover - depends on the environment
            pytest.skip(f"{NO_MYSQL_REASON}: {error}")

    import psycopg2

    try:
        return PsycopgDriver.connect(dsn_from_env()), PostgresDialect()
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")


@pytest.fixture(params=["postgres", "mysql", "sqlite"])
def loaded(request: pytest.FixtureRequest) -> Iterator[AllTypes]:
    """The row written and READ BACK from the engine of this parameter."""
    driver, dialect = _connector(str(request.param))
    table = snake_table(AllTypes)
    try:
        driver.execute(
            emit_drop_table(table, dialect).replace(
                "DROP TABLE", "DROP TABLE IF EXISTS"
            ),
            (),
        )
        driver.commit()
        driver.execute(emit_create_table(table, dialect), ())
        driver.commit()
        session = SnakeSession(driver, dialect)
        _SESSION[0] = session
        session.add(AllTypes(**_EXPECTED))  # type: ignore[arg-type]
        session.commit()
        row = session.first(SnakeQuery(AllTypes))
        assert row is not None
        yield row
    finally:
        try:
            driver.execute(emit_drop_table(table, dialect), ())
            driver.commit()
        finally:
            driver.close()


@pytest.mark.parametrize("field", sorted(_EXPECTED), ids=str)
def test_the_value_survives_the_round_trip(field: str, loaded: AllTypes) -> None:
    """The value comes back THE SAME. It is the obvious half, and the one that catches an INSERT that does not even work."""
    assert getattr(loaded, field) == _EXPECTED[field]


@pytest.mark.parametrize("field", sorted(_EXPECTED), ids=str)
def test_the_declared_type_is_the_type_you_get_back(
    field: str, loaded: AllTypes
) -> None:
    """And it comes back with ITS TYPE, which is the whole promise of the project.

    It is the less obvious half and the one that catches the silent failures: a `bool` that comes
    back as `1`, a `Decimal` that comes back as `float`, an enum that comes back as the raw `str`.
    With a `StrEnum` the last one does not even break the comparison —`'closed' == State.CLOSED` is
    `True`— so without checking the type, that bug is invisible.
    """
    expected = _EXPECTED[field]
    if expected is None:
        assert getattr(loaded, field) is None
        return

    assert type(getattr(loaded, field)) is type(expected)


def test_every_supported_type_is_in_this_file() -> None:
    """The matrix covers ALL the types the dialect claims to map. If a new one shows up, it fails.

    It is the half that makes the rest useful: a matrix over an incomplete list passes just as
    green, and that trap has already shown up in this branch more than once. The list is taken from
    the DIALECT, not from my memory.
    """
    from snakeorm.dialects.postgres import _POSTGRES_TYPES

    declared = {type_ for type_ in _POSTGRES_TYPES if isinstance(type_, type)}
    covered = {column.python_type for column in snake_table(AllTypes).columns} | {
        bool,
        int,
        str,
    }  # the ones that come in by another route (PK, enums stored as text)

    missing = {t.__name__ for t in declared - covered}

    assert missing == set(), (
        f"types the dialect maps and this matrix does not test: {sorted(missing)}"
    )


@pytest.mark.parametrize(
    "field",
    ["public_id", "exact_amount", "instant", "day", "document", "status"],
    ids=str,
)
def test_you_can_also_FILTER_by_a_value_of_that_type(
    field: str, loaded: AllTypes
) -> None:
    """And you can FILTER by it, not just write it and read it.

    It is the edge the tests above do not touch: they insert and read without a `WHERE`. A value
    that is written correctly but does not match when compared gives ZERO ROWS without a single
    error — the most expensive silent failure in an ORM, because it looks like there is simply no
    data.

    Today it works because of a LAYERING decision: the adaptation to the DBAPI lives in the driver,
    so the `WHERE` inherits it just like the `INSERT` does. The first version put it in the
    emitters, and there this test would have stayed green while the DDL broke. This case exists so
    that moving that logic elsewhere breaks something visible again.
    """
    value = _EXPECTED[field]
    column = getattr(AllTypes, field)

    found = _SESSION[0].first(SnakeQuery(AllTypes).filter(column == value))

    assert found is not None, f"filtering by {field}={value!r} returned zero rows"


@pytest.mark.parametrize("engine", ["postgres", "sqlite"], ids=str)
def test_a_model_with_only_an_autoincrement_pk_can_be_inserted(engine: str) -> None:
    """A model whose ONLY column is the autoincrement PK can be inserted. On both engines.

    A legitimate schema —an entity defined by its id and its relationships, one end of an m2m— that
    could not be inserted on ANY engine: `emit_insert` blew up with "necesita al menos una columna
    con valor". `INSERT ... DEFAULT VALUES` is standard and both understand it. The three write
    paths are tested: `add`, `add_all` (which falls back to row-by-row insertion, there is no
    portable all-default multi-row) and that `upsert` stops with a clear message instead of the
    engine's `near "ON"`.
    """
    from snakeorm.core.exceptions import SnakeEmitError
    from snakeorm.migration import emit_drop_table

    driver, dialect = _connector(engine)
    table = snake_table(_SoloId)
    try:
        driver.execute(emit_create_table(table, dialect), ())
        driver.commit()
        s = SnakeSession(driver, dialect)

        a = _SoloId()
        s.add(a)
        s.commit()
        assert a.id is not None, "add of an id-only model: the server assigns the id"

        b, c = _SoloId(), _SoloId()
        s.add_all([b, c])
        s.commit()
        assert b.id is not None and c.id is not None, "add_all too"

        with pytest.raises(
            SnakeEmitError, match="An upsert needs at least one value to insert"
        ):
            s.upsert(_SoloId(), on_conflict=[_SoloId.id])  # type: ignore[list-item]
    finally:
        try:
            driver.execute(emit_drop_table(table, dialect), ())
            driver.commit()
        finally:
            driver.close()
