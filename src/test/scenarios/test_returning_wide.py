"""Integration: the wide RETURNING brings back the values the SERVER puts in, on every engine that has it.

A column with a server default that is NOT part of the INSERT is filled in by the database. The
RETURNING used to ask only for the PK, so that value never reached the in-memory object; now it
lists every column and `session.add()` assigns them back, coerced.

**Two engines run it and the third declares it cannot**, which is the whole claim. It used to run on
Postgres alone while SQLite answers `Cap.RETURNING: Full()` — it has had the clause since 3.35 — so
the one engine most likely to spell it differently was the one nobody tried. MySQL is not missing
from this file: `test_mysql_says_it_cannot_and_that_is_why_it_is_absent` is why it is not here, and
it fails the day that stops being true.

The table is built by the ORM rather than by hand-written DDL: a `CREATE TABLE` typed into a test is
a second opinion about the schema, and it was already drifting — the old one said `::timestamp`
where the model said `TIMESTAMPTZ`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest

from snakeorm import SnakeUtc, snake_datetimetz
from snakeorm.decorators import snake_model, snake_table
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.dialects.base import SnakeDialect
from snakeorm.dialects.capabilities import Cap, Nope
from snakeorm.drivers import PsycopgDriver, SQLiteDriver
from snakeorm.drivers.base import SnakeDriver
from snakeorm.fields import SnakeColumn, snake_auto, snake_str
from snakeorm.metadata import SnakeServerDefault
from snakeorm.migration import emit_create_table
from snakeorm.model import SnakeModel
from snakeorm.session import SnakeSession
from test.conftest import NO_SERVER_REASON
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_TABLE = "rw_notes"


@snake_model(prefix="rw")
class Note(SnakeModel):
    """Note with an autoincrement PK and a created_at the server fills in (`server_default`)."""

    id: SnakeColumn[int] = snake_auto()
    text: SnakeColumn[str] = snake_str()
    # The DB puts the value in: the column is excluded from __init__/INSERT and RETURNING brings it.
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )


def _start(driver: SnakeDriver, dialect: SnakeDialect) -> SnakeSession:
    """Create the table through the ORM and hand back a session on it."""
    driver.execute(f"DROP TABLE IF EXISTS {_TABLE}", ())
    driver.execute(emit_create_table(snake_table(Note), dialect), ())
    driver.commit()
    return SnakeSession(driver, dialect)


@pytest.fixture
def postgres() -> Iterator[SnakeSession]:
    """A real Postgres session with the table created by the ORM."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except psycopg2.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    yield _start(driver, PostgresDialect())
    driver.execute(f"DROP TABLE IF EXISTS {_TABLE}", ())
    driver.commit()
    driver.close()


@pytest.fixture
def sqlite() -> Iterator[SnakeSession]:
    """An in-memory SQLite session. It has RETURNING since 3.35 and nobody was exercising it."""
    driver = SQLiteDriver.connect(":memory:")
    yield _start(driver, SQLiteDialect())
    driver.close()


_ENGINES = ["postgres", "sqlite"]


def _now(session: SnakeSession) -> datetime:
    """The engine's own clock, asked for in its own spelling.

    Not Python's: the point is that the value comes from the SERVER, and comparing against the
    client's clock would pass on a machine whose two clocks disagree and fail on one that does not.
    """
    stamp = session._driver.fetch_all(  # noqa: SLF001
        f"SELECT {session.dialect.server_default_sql(SnakeServerDefault.NOW)}", ()
    )[0][0]
    return stamp if isinstance(stamp, datetime) else datetime.fromisoformat(str(stamp))


@pytest.mark.parametrize("engine", _ENGINES)
def test_add_fills_the_server_default_from_returning(
    engine: str, request: pytest.FixtureRequest
) -> None:
    """A `created_at` the INSERT never mentions comes back on the object, filled in by the database."""
    session: SnakeSession = request.getfixturevalue(engine)
    before = _now(session)

    note = Note(text="hola")
    session.add(note)
    session.commit()

    assert isinstance(note.created_at, datetime)
    assert note.created_at.replace(tzinfo=None) >= before.replace(tzinfo=None)


@pytest.mark.parametrize("engine", _ENGINES)
def test_add_also_fills_the_autoincrement_pk(
    engine: str, request: pytest.FixtureRequest
) -> None:
    """The same wide RETURNING still fills in the key the engine generated."""
    session: SnakeSession = request.getfixturevalue(engine)

    note = Note(text="other")
    session.add(note)
    session.commit()

    assert isinstance(note.id, int)
    assert note.id >= 1


def test_mysql_says_it_cannot_and_that_is_why_it_is_absent() -> None:
    """MySQL is missing from the run above because it DECLARES it has no RETURNING.

    Written down so the absence is a decision rather than a gap somebody stopped noticing. The day
    MySQL grows the clause and the dialect says so, this fails and the engine joins the list.
    """
    support = MySQLDialect().capabilities.support_for(Cap.RETURNING)

    assert isinstance(support, Nope), (
        f"MySQL now answers {type(support).__name__} for RETURNING: add it to _ENGINES"
    )
    assert "RETURNING" in support.reason
