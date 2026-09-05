"""Integration against a real Postgres: bulk writes, `in_(subquery)` and `distinct()`.

It is not enough for the SQL to "not blow up": you have to check VALUES in the DB. It seeds its OWN
domain (tables `lab5_*`, unique so as not to clash with other scenarios in the global registry) and
each test re-creates the schema, so the mutations (update/delete) do not contaminate one another. It
checks that `update_where` with `col = col + 1` changes the right values and returns the rowcount,
that `delete_where` leaves the expected rows, that `in_(subquery)` filters by the result of another
query and that `distinct()` collapses duplicates.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.drivers.psycopg import PsycopgDriver
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="lab5_zones")
class Zone(SnakeModel):
    """Zone (parent of the subquery): North and South."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="lab5_squads")
class Squad(SnakeModel):
    """Squad with a zone (by id) and a hit counter that gets updated in bulk."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    zone_id: SnakeColumn[int] = snake_int()
    hits: SnakeColumn[int] = snake_int()


_DDL = (
    "DROP TABLE IF EXISTS lab5_squads, lab5_zones CASCADE",
    "CREATE TABLE lab5_zones (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE lab5_squads ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
    " zone_id INTEGER NOT NULL, hits INTEGER NOT NULL)",
)

# Zones: North(1), South(2). Squads: 3 in North (repeated zone_id → exercises DISTINCT).
_SEED = (
    "INSERT INTO lab5_zones VALUES (1, 'North'), (2, 'South')",
    "INSERT INTO lab5_squads VALUES"
    " (1, 'Alpha', 1, 10), (2, 'Bravo', 1, 20),"
    " (3, 'Cobra', 2, 5), (4, 'Delta', 2, 7), (5, 'Echo', 1, 3)",
)


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Session against the real Postgres; re-creates and seeds the schema in EACH test (isolation)."""
    try:
        connection = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    driver = PsycopgDriver(connection)
    for statement in (*_DDL, *_SEED):
        driver.execute(statement, ())
    driver.commit()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.close()


def test_update_where_increments_and_returns_rowcount(session: SnakeSession) -> None:
    """`update_where` with `hits = hits + 10` over North changes ONLY those rows and returns 3."""
    affected = session.update_where(
        SnakeQuery(Squad).filter(Squad.zone_id == 1), [(Squad.hits, Squad.hits + 10)]
    )
    assert affected == 3
    north = session.all(SnakeQuery(Squad).filter(Squad.zone_id == 1))
    assert sorted(squad.hits for squad in north) == [13, 20, 30]
    south = session.all(SnakeQuery(Squad).filter(Squad.zone_id == 2))
    assert sorted(squad.hits for squad in south) == [5, 7]


def test_delete_where_removes_matching_rows_and_returns_rowcount(
    session: SnakeSession,
) -> None:
    """`delete_where` with a filter deletes ONLY 'Cobra' (rowcount 1) and leaves the rest."""
    affected = session.delete_where(SnakeQuery(Squad).filter(Squad.name == "Cobra"))
    assert affected == 1
    remaining = session.all(SnakeQuery(Squad))
    assert sorted(squad.id for squad in remaining) == [1, 2, 4, 5]


def test_in_subquery_returns_the_right_rows(session: SnakeSession) -> None:
    """`zone_id IN (SELECT id FROM zones WHERE name='North')` returns the squads from North."""
    subquery = SnakeQuery(Zone).filter(Zone.name == "North").as_scalar(Zone.id)
    squads = session.all(SnakeQuery(Squad).filter(Squad.zone_id.in_(subquery)))
    assert sorted(squad.id for squad in squads) == [1, 2, 5]


def test_distinct_collapses_duplicate_values(session: SnakeSession) -> None:
    """`distinct()` over `zone_id` (with duplicates) collapses to the two unique values."""
    rows = session.select(SnakeQuery(Squad).distinct(), Squad.zone_id)
    assert sorted(zone_id for (zone_id,) in rows) == [1, 2]
