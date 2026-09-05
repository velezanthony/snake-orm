"""Integration: `add_all()` inserts a batch in a single multi-row INSERT and fills in the PKs.

~150 rows of a table with few columns are inserted: they all arrive and the autoincrement PKs
are assigned back to each instance IN ORDER (via the wide RETURNING). Chunking by the dialect's
parameter ceiling is tested separately (a unit test, with a small max_bind_params).

Against a real Postgres: the SQL is actually executed.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver
from snakeorm.fields import SnakeColumn, snake_auto, snake_int

from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_ROWS = 150


@snake_model(prefix="ba")
class Tick(SnakeModel):
    """Minimal row: autoincrement PK + one integer, for bulk inserting."""

    id: SnakeColumn[int] = snake_auto()
    value: SnakeColumn[int] = snake_int()


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Session against a real Postgres with the ba_ticks table empty."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    driver.execute("DROP TABLE IF EXISTS ba_ticks", ())
    driver.execute(
        "CREATE TABLE ba_ticks (id SERIAL PRIMARY KEY, value INTEGER NOT NULL)", ()
    )
    driver.commit()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.execute("DROP TABLE IF EXISTS ba_ticks", ())
        driver.commit()
        driver.close()


def test_add_all_inserts_every_row(session: SnakeSession) -> None:
    """Checks that the 150 rows reach the DB (count and sum of values)."""
    ticks = [Tick(value=i) for i in range(_ROWS)]
    session.add_all(ticks)
    session.commit()
    stored = session.all(SnakeQuery(Tick))
    assert len(stored) == _ROWS
    assert sorted(tick.value for tick in stored) == list(range(_ROWS))


def test_add_all_fills_autoincrement_pks_in_order(session: SnakeSession) -> None:
    """Checks that each instance gets its generated autoincrement PK, distinct and in order."""
    ticks = [Tick(value=i) for i in range(_ROWS)]
    session.add_all(ticks)
    session.commit()
    ids = [tick.id for tick in ticks]
    assert all(isinstance(pk, int) for pk in ids)
    assert len(set(ids)) == _ROWS  # all distinct
    assert ids == sorted(ids)  # the RETURNING respects the order of the VALUES
