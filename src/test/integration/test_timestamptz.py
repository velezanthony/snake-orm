"""INTEGRATION: the TWO date types of Postgres, against a real server.

`TIMESTAMPTZ` stores an INSTANT: the moment survives the journey even if the zone used to represent
it changes. `TIMESTAMP` stores a WALL CLOCK TIME: Postgres DISCARDS the `tzinfo` on write and hands
back a naive one. It does not fail, it does not warn; it simply gives you the wrong time, and you
only notice when somebody is in another zone.

What changed is whose decision it is. Before, every `datetime` went to `TIMESTAMPTZ` and the wall
clock time could not even be declared; now the model says so —`snake_datetimetz()` with
`SnakeColumn[SnakeUtc]` or `snake_datetime()` with `SnakeColumn[datetime]`— and a guard demands that
both halves match.

That is why this file tests BOTH. Checking only the good one would leave without a net precisely the
half that loses data, which is the one that has to be provably losing data ON PURPOSE. And it is not
theoretical: while this suite could not be run, the scaffolder had been emitting `snake_datetime()`
for `TIMESTAMPTZ` columns — a file that did not even import.

It skips gracefully when there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import SnakeUtc
from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeDateTimeParams,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import emit_create_table
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_MADRID = timezone(timedelta(hours=2))
_INSTANT = datetime(2026, 8, 10, 14, 30, tzinfo=_MADRID)


@pytest.fixture
def driver() -> Iterator[PsycopgDriver]:
    """Driver against the real Postgres with `tz_probe` created by the ORM's own DDL.

    The table carries ONE column of each type, created by the same emitter a real migration uses:
    what is checked below is what a user would have in front of them.
    """
    import psycopg2

    try:
        connection = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    identifier = SnakeColumnInfo(name="id", python_type=int)
    table = SnakeTableInfo(
        name="tz_probe",
        columns=(
            identifier,
            SnakeColumnInfo(
                name="happened_at",
                python_type=SnakeUtc,
                nullable=True,  # each test writes ONE of the two columns
                type_params=SnakeDateTimeParams(tz=True),
            ),
            SnakeColumnInfo(
                name="wall_clock",
                python_type=datetime,
                nullable=True,
                type_params=SnakeDateTimeParams(tz=False),
            ),
        ),
        primary_key=SnakePrimaryKeyInfo(columns=(identifier,)),
    )
    connection.execute("DROP TABLE IF EXISTS tz_probe", ())
    connection.execute(emit_create_table(table, PostgresDialect()), ())
    connection.commit()
    try:
        yield connection
    finally:
        connection.execute("DROP TABLE IF EXISTS tz_probe", ())
        connection.commit()
        connection.close()


def _type_of(driver: PsycopgDriver, column: str) -> str:
    """The type the Postgres CATALOGUE says that column has."""
    rows = driver.fetch_all(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'tz_probe' AND column_name = %s",
        (column,),
    )
    return str(rows[0][0])


def test_each_declarator_creates_the_type_it_says(driver: PsycopgDriver) -> None:
    """Checks against the catalogue that each declarator creates the type it announces.

    It is the check no unit test can give: the DDL we emit could be syntactically valid and create
    something else entirely. Here it is the server itself doing the talking.
    """
    assert _type_of(driver, "happened_at") == "timestamp with time zone"
    assert _type_of(driver, "wall_clock") == "timestamp without time zone"


def test_an_aware_datetime_survives_the_round_trip(driver: PsycopgDriver) -> None:
    """Checks that in the column WITH a zone the instant comes back intact, not a mangled naive."""
    driver.execute(
        "INSERT INTO tz_probe (id, happened_at) VALUES (%s, %s)", (1, _INSTANT)
    )
    driver.commit()

    returned = driver.fetch_all("SELECT happened_at FROM tz_probe WHERE id = %s", (1,))[
        0
    ][0]

    assert isinstance(returned, datetime)
    assert returned.tzinfo is not None, (
        "a column with a zone cannot give back a naive one"
    )
    assert returned == _INSTANT  # the same instant, even if represented in another zone


def test_two_representations_of_the_same_instant_are_equal(
    driver: PsycopgDriver,
) -> None:
    """Checks that in the column WITH a zone it is the INSTANT that is compared, not the clock face.

    14:30 at UTC+2 and 12:30 at UTC are the SAME moment. Without a zone, each one is stored with its
    own wall clock time and they come out different: 14:30 != 12:30. That is the silent bug avoided.
    """
    driver.execute(
        "INSERT INTO tz_probe (id, happened_at) VALUES (%s, %s)", (1, _INSTANT)
    )
    driver.execute(
        "INSERT INTO tz_probe (id, happened_at) VALUES (%s, %s)",
        (2, _INSTANT.astimezone(timezone.utc)),
    )
    driver.commit()

    rows = driver.fetch_all("SELECT happened_at FROM tz_probe ORDER BY id", ())

    assert rows[0][0] == rows[1][0]


def test_the_wall_clock_column_really_does_drop_the_zone(
    driver: PsycopgDriver,
) -> None:
    """Checks that the column WITHOUT a zone loses the zone, which is its declared behaviour.

    This test asserts a LOSS of information, and it is on purpose: `snake_datetime()` exists to
    store a wall clock time —a shop opening is 9:00 in whichever city it stands in— and whoever
    declares it has to be able to trust that this is what happens.

    It is also the proof that the compiler guard protects against something REAL: putting an instant
    in here mangles it, and that is why `SnakeColumn[SnakeUtc]` with this declarator is a compile
    error.
    """
    driver.execute(
        "INSERT INTO tz_probe (id, wall_clock) VALUES (%s, %s)", (1, _INSTANT)
    )
    driver.commit()

    returned = driver.fetch_all("SELECT wall_clock FROM tz_probe WHERE id = %s", (1,))[
        0
    ][0]

    assert isinstance(returned, datetime)
    assert returned.tzinfo is None, (
        "a column without a zone cannot give back an aware one"
    )
    assert returned.hour == 14, (
        "it stores the WALL-CLOCK time exactly as written, without converting"
    )
