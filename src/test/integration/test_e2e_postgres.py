"""INTEGRATION smoke test: the whole SnakeORM stack against a REAL Postgres.

Closes the one link the unit tests do not cover: that the SQL emitted really does execute on
Postgres through psycopg2 (INSERT ... RETURNING, SELECT ... WHERE, UPDATE, DELETE) and that
the rows round-trip back into typed instances.

SKIPPED gracefully when no Postgres is available. The DSN comes from the .env (shared helper
test.scenarios.db.dsn), the single source of the connection.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="smoke_users")
class SmokeUser(SnakeModel):
    """Smoke test model (explicit PK, no serial)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    username: SnakeColumn[str] = snake_str()
    age: SnakeColumn[int] = snake_int()


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Opens a session against the real Postgres and sets up/tears down the test table."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    driver.execute("DROP TABLE IF EXISTS smoke_users", ())
    driver.execute(
        "CREATE TABLE smoke_users "
        "(id INTEGER PRIMARY KEY, username TEXT NOT NULL, age INTEGER NOT NULL)",
        (),
    )
    driver.commit()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.execute("DROP TABLE IF EXISTS smoke_users", ())
        driver.commit()
        driver.close()


def test_full_crud_round_trip(session: SnakeSession) -> None:
    """Checks the full cycle against a real Postgres: add → read → update → delete."""
    # INSERT ... RETURNING on a real Postgres
    session.add(SmokeUser(id=1, username="Ana", age=30))
    session.add(SmokeUser(id=2, username="Bob", age=15))
    session.commit()

    # SELECT: round-trip back into typed instances
    everyone = session.all(SnakeQuery(SmokeUser))
    assert {(u.id, u.username, u.age) for u in everyone} == {
        (1, "Ana", 30),
        (2, "Bob", 15),
    }

    # SELECT ... WHERE
    adults = session.all(SnakeQuery(SmokeUser).filter(SmokeUser.age >= 18))
    assert [u.username for u in adults] == ["Ana"]

    # first
    bob = session.first(SnakeQuery(SmokeUser).filter(SmokeUser.username == "Bob"))
    assert bob is not None
    assert bob.age == 15

    # UPDATE
    bob.age = 21
    session.update(bob)
    session.commit()
    bob_updated = session.first(SnakeQuery(SmokeUser).filter(SmokeUser.id == 2))
    assert bob_updated is not None
    assert bob_updated.age == 21

    # DELETE
    session.delete(SmokeUser(id=1, username="Ana", age=30))
    session.commit()
    remaining = session.all(SnakeQuery(SmokeUser))
    assert [u.id for u in remaining] == [2]
