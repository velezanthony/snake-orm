"""INTEGRATION: `ABS` and `ROUND` return the right ROWS on all three engines.

This is the test whose absence let the bug through. `ABS` and `ROUND` were missing from SQLite's
translation table while Postgres and MySQL had both, and nothing went red: the maths functions were
covered by tests that assert the emitted SQL STRING, which is the same string on every engine and so
says nothing about whether any engine will run it. A model that worked on two raised
`SQLiteDialect cannot translate ABS` on the third, and only using it would tell you.

So this one EXECUTES and reads the values back — and doing that immediately turned up a second
one: Postgres has `ROUND(double precision)` and `ROUND(numeric, int)`, but NOT
`ROUND(double precision, int)`, which is what the ORM emits for `snake_round(a_float, digits)`.
It needs a dialect hook the emitter does not have
yet, so what is asserted here is the single-argument form, which every engine does have.

Skipped gracefully when an engine is not reachable, and turned into a failure by the
`SNAKEORM_REQUIRE_*` gates.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

import pytest

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    PsycopgDriver,
    PyMySQLDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SQLiteDialect,
    SQLiteDriver,
    snake_float,
    snake_int,
    snake_model,
    snake_table,
)
from snakeorm.dialects.base import SnakeDialect
from snakeorm.drivers.base import SnakeDriver
from snakeorm.expressions import (
    snake_abs,
    snake_ceil,
    snake_floor,
    snake_power,
    snake_round,
    snake_sqrt,
)
from snakeorm.migration import emit_create_table
from test.conftest import NO_MYSQL_REASON, NO_SERVER_REASON
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="maths_readings")
class Reading(SnakeModel):
    """Signed readings, so `ABS` has something to do."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    delta: SnakeColumn[int] = snake_int()
    amount: SnakeColumn[float] = snake_float()


_TABLE = "maths_readings"
_ROWS = [(1, -7, 2.34), (2, 3, -8.76), (3, 0, 0.5)]

# `2.34` and `-8.76` on purpose: neither is a half, so every engine rounds them the same way and the
# expected value is arithmetic rather than a policy. `0.5` is seeded and never asserted rounded —
# half-away-from-zero and half-to-even disagree there, and picking one would assert an engine's
# taste while claiming to check the ORM.
_ROUNDED = {1: 2.0, 2: -9.0}


def _seed(driver: SnakeDriver, dialect: SnakeDialect) -> SnakeSession:
    """Create the table through the ORM, seed it, and hand back the session on it."""
    session = SnakeSession(driver, dialect)
    driver.execute(f"DROP TABLE IF EXISTS {_TABLE}", ())
    driver.execute(emit_create_table(snake_table(Reading), dialect), ())
    for row_id, delta, amount in _ROWS:
        session.add(Reading(id=row_id, delta=delta, amount=amount))
    session.commit()
    return session


@pytest.fixture
def postgres() -> Iterator[SnakeSession]:
    """A real Postgres session, seeded."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except psycopg2.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    yield _seed(driver, PostgresDialect())
    driver.execute(f"DROP TABLE IF EXISTS {_TABLE}", ())
    driver.commit()
    driver.close()


@pytest.fixture
def mysql() -> Iterator[SnakeSession]:
    """A real MySQL session, seeded."""
    host = os.environ.get("MYSQL_HOST")
    if not host:
        pytest.skip(f"{NO_MYSQL_REASON}: MYSQL_HOST is not set")
    import pymysql

    try:
        driver = PyMySQLDriver.connect(
            host=host,
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ.get("MYSQL_DB", "snakeorm_db"),
        )
    except pymysql.err.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_MYSQL_REASON}: {error}")

    yield _seed(driver, MySQLDialect())
    driver.execute(f"DROP TABLE IF EXISTS {_TABLE}", ())
    driver.commit()
    driver.close()


@pytest.fixture
def sqlite() -> Iterator[SnakeSession]:
    """An in-memory SQLite session, seeded. The engine this batch was broken on."""
    driver = SQLiteDriver.connect(":memory:")
    yield _seed(driver, SQLiteDialect())
    driver.close()


_ENGINES = ["postgres", "mysql", "sqlite"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_abs_brings_back_the_magnitude(
    engine: str, request: pytest.FixtureRequest
) -> None:
    """`ABS` runs on the engine and the rows come back positive, on all three."""
    session: SnakeSession = request.getfixturevalue(engine)

    rows = session.select(
        SnakeQuery(Reading).order_by(Reading.id.asc()),
        Reading.id,
        snake_abs(Reading.delta),
    )

    assert [(row_id, int(size)) for row_id, size in rows] == [(1, 7), (2, 3), (3, 0)]


@pytest.mark.parametrize("engine", _ENGINES)
def test_round_brings_back_the_rounded_value(
    engine: str, request: pytest.FixtureRequest
) -> None:
    """`ROUND(x)` runs on the engine and the rows carry the rounded number, on all three.

    No digits, and the two readings that are not halves: what is checked is that the ORM reaches the
    engine's own function and the value survives the trip, not which way each engine breaks a tie.
    The two-argument form lives in its own test below, because for a long time it did not work.
    """
    session: SnakeSession = request.getfixturevalue(engine)

    rows = session.select(
        SnakeQuery(Reading)
        .filter(Reading.id.in_(list(_ROUNDED)))
        .order_by(Reading.id.asc()),
        Reading.id,
        snake_round(Reading.amount),
    )

    assert {row_id: float(Decimal(str(tidy))) for row_id, tidy in rows} == _ROUNDED


# `2.3` and `-8.8`: one decimal place, and neither input is a half there either, so the expected
# value stays arithmetic rather than an engine's tie-breaking taste.
_ROUNDED_TO_ONE = {1: 2.3, 2: -8.8}


@pytest.mark.parametrize("engine", _ENGINES)
def test_round_takes_a_digit_count_on_every_engine(
    engine: str, request: pytest.FixtureRequest
) -> None:
    """`ROUND(x, 1)` over a FLOAT column, on all three. This was bug #34's open half.

    Postgres has `ROUND(double precision)` and `ROUND(numeric, int)` and no `ROUND(double
    precision, int)`, so the two-argument call reached the engine and came back
    `function round(double precision, integer) does not exist` — an error from the DRIVER explaining
    a decision this ORM made, which is the shape the project refuses everywhere else.

    The other two engines round a float with a digit count directly, so this asserts the VALUE and
    not a per-engine spelling: whatever the dialect does to get there, the number is the same.
    """
    session: SnakeSession = request.getfixturevalue(engine)

    rows = session.select(
        SnakeQuery(Reading)
        .filter(Reading.id.in_(list(_ROUNDED_TO_ONE)))
        .order_by(Reading.id.asc()),
        Reading.id,
        snake_round(Reading.amount, 1),
    )

    assert {
        row_id: float(Decimal(str(tidy))) for row_id, tidy in rows
    } == _ROUNDED_TO_ONE


# -- The four that were translated on all three engines and executed on NONE ----------------------
#
# `ABS` and `ROUND` were missing from SQLite's table and that was bug #34. These four are IN the
# three tables, and until now no engine had ever run them: the net above them asserted the emitted
# SQL, which is the same string everywhere and therefore says nothing about any engine.


@contextmanager
def _tolerating_a_sqlite_without_maths(engine: str) -> Iterator[None]:
    """SQLite's maths are a BUILD option (`ENABLE_MATH_FUNCTIONS`), not a capability.

    A `Cap` is answered by the dialect CLASS, which cannot know which binary got linked, so this
    cannot be declared — it has to be asked. Asking it by running the query is the whole probe: a
    separate `SELECT ceil(1.2)` would be a second thing to keep in step with the first.
    """
    try:
        yield
    except sqlite3.OperationalError as error:  # pragma: no cover - depends on the build
        if engine == "sqlite" and "no such function" in str(error):
            pytest.skip(f"SQLite built without ENABLE_MATH_FUNCTIONS: {error}")
        raise


_CEILED = {1: 3.0, 2: -8.0, 3: 1.0}
_FLOORED = {1: 2.0, 2: -9.0, 3: 0.0}


@pytest.mark.parametrize("engine", _ENGINES)
def test_ceil_rounds_up_on_every_engine(
    engine: str, request: pytest.FixtureRequest
) -> None:
    """`CEIL` runs and the rows carry the value rounded UP, negatives included.

    `-8.76 -> -8` is the half that a sign mistake gets wrong: rounding up means towards zero here.
    """
    session: SnakeSession = request.getfixturevalue(engine)

    with _tolerating_a_sqlite_without_maths(engine):
        rows = session.select(
            SnakeQuery(Reading).order_by(Reading.id.asc()),
            Reading.id,
            snake_ceil(Reading.amount),
        )

        assert {row_id: float(value) for row_id, value in rows} == _CEILED


@pytest.mark.parametrize("engine", _ENGINES)
def test_floor_rounds_down_on_every_engine(
    engine: str, request: pytest.FixtureRequest
) -> None:
    """`FLOOR` runs and rounds DOWN. `-8.76 -> -9`, which is away from zero."""
    session: SnakeSession = request.getfixturevalue(engine)

    with _tolerating_a_sqlite_without_maths(engine):
        rows = session.select(
            SnakeQuery(Reading).order_by(Reading.id.asc()),
            Reading.id,
            snake_floor(Reading.amount),
        )

        assert {row_id: float(value) for row_id, value in rows} == _FLOORED


@pytest.mark.parametrize("engine", _ENGINES)
def test_power_raises_on_every_engine(
    engine: str, request: pytest.FixtureRequest
) -> None:
    """`POWER(x, 2)` runs, and the exponent travels as a PARAMETER rather than in the string."""
    session: SnakeSession = request.getfixturevalue(engine)

    with _tolerating_a_sqlite_without_maths(engine):
        rows = session.select(
            SnakeQuery(Reading).order_by(Reading.id.asc()),
            Reading.id,
            snake_power(Reading.delta, 2),
        )

        assert {row_id: float(value) for row_id, value in rows} == {
            1: 49.0,
            2: 9.0,
            3: 0.0,
        }


@pytest.mark.parametrize("engine", _ENGINES)
def test_sqrt_runs_over_another_function_on_every_engine(
    engine: str, request: pytest.FixtureRequest
) -> None:
    """`SQRT` runs, and nesting it over `POWER` makes the expected value exact instead of a decimal.

    `sqrt(delta^2)` is `|delta|`, so the assertion is integers and not a rounding policy — and it
    proves the two compose, which one function on its own cannot say.
    """
    session: SnakeSession = request.getfixturevalue(engine)

    with _tolerating_a_sqlite_without_maths(engine):
        rows = session.select(
            SnakeQuery(Reading).order_by(Reading.id.asc()),
            Reading.id,
            snake_sqrt(snake_power(Reading.delta, 2)),
        )

        assert {row_id: float(value) for row_id, value in rows} == {
            1: 7.0,
            2: 3.0,
            3: 0.0,
        }
