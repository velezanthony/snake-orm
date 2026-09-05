"""Integration against a real Postgres: BULK writes with a WHERE that crosses a relationship.

It is not enough for the SQL to "not blow up": you have to check VALUES in the DB. An OWN domain is
seeded (tables `dwe_*`, unique so as not to clash with other scenarios in the global registry; and
globally unique model NAMES, because the registry is global and collides by `__name__`). Each test
re-creates and seeds the schema, so the mutations do not contaminate one another.

It checks that an `update_where` filtering by a column of the PARENT updates ONLY the CHILD rows
hanging off that parent (with the right rowcount), that an analogous `delete_where` deletes exactly
those rows, and that with a COMPOSITE PK the distribution is still exact (row constructor in the
subquery).
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.drivers.psycopg import PsycopgDriver
from snakeorm.fields import (
    SnakeColumn,
    SnakeToOne,
    snake_column,
    snake_int,
    snake_str,
    snake_to_one,
)

from snakeorm.linker.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="dwe_hubs")
class Hub(SnakeModel):
    """Hub (parent): Central and Regional."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="dwe_pods")
class Pod(SnakeModel):
    """Pod (child) with a hub by FK and an `active` flag that gets updated in bulk."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    label: SnakeColumn[str] = snake_str()
    hub_id: SnakeColumn[int] = snake_int()
    active: SnakeColumn[bool] = snake_column()
    hub: SnakeToOne[Hub] = snake_to_one(hub_id)


@snake_model(table="dwe_sectors")
class Sector(SnakeModel):
    """Sector (parent) of the composite-PK domain."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="dwe_lots")
class Lot(SnakeModel):
    """Lot (child) with a COMPOSITE PK (region, code) and an FK to Sector: exercises the real tuple-in."""

    region: SnakeColumn[str] = snake_str(primary_key=True)
    code: SnakeColumn[int] = snake_int(primary_key=True)
    sector_id: SnakeColumn[int] = snake_int()
    weight: SnakeColumn[int] = snake_int()
    sector: SnakeToOne[Sector] = snake_to_one(sector_id)


_DDL = (
    "DROP TABLE IF EXISTS dwe_pods, dwe_hubs, dwe_lots, dwe_sectors CASCADE",
    "CREATE TABLE dwe_hubs (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE dwe_pods ("
    " id INTEGER PRIMARY KEY, label TEXT NOT NULL,"
    " hub_id INTEGER NOT NULL REFERENCES dwe_hubs(id), active BOOLEAN NOT NULL)",
    "CREATE TABLE dwe_sectors (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE dwe_lots ("
    " region TEXT NOT NULL, code INTEGER NOT NULL,"
    " sector_id INTEGER NOT NULL REFERENCES dwe_sectors(id), weight INTEGER NOT NULL,"
    " PRIMARY KEY (region, code))",
)

# Central(1) has Pods 1 and 2; Regional(2) has Pod 3. They all start out active.
# Sector Alpha(1) has lots (North,1) and (North,2); Beta(2) has (South,1).
_SEED = (
    "INSERT INTO dwe_hubs VALUES (1, 'Central'), (2, 'Regional')",
    "INSERT INTO dwe_pods VALUES"
    " (1, 'A', 1, TRUE), (2, 'B', 1, TRUE), (3, 'C', 2, TRUE)",
    "INSERT INTO dwe_sectors VALUES (1, 'Alpha'), (2, 'Beta')",
    "INSERT INTO dwe_lots VALUES"
    " ('North', 1, 1, 10), ('North', 2, 1, 20), ('South', 1, 2, 5)",
)


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Session against the real Postgres; re-creates and seeds the schema in EACH test (isolation)."""
    try:
        connection = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    snake_link()
    driver = PsycopgDriver(connection)
    for statement in (*_DDL, *_SEED):
        driver.execute(statement, ())
    driver.commit()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.close()


def test_update_where_deep_updates_only_the_children_of_the_matched_parent(
    session: SnakeSession,
) -> None:
    """Filtering by the PARENT 'Central' and setting `active=False` changes ONLY its 2 Pods (rowcount 2)."""
    affected = session.update_where(
        SnakeQuery(Pod).filter(Pod.hub.name == "Central"), [(Pod.active, False)]
    )
    assert affected == 2
    pods = {pod.id: pod.active for pod in session.all(SnakeQuery(Pod))}
    assert pods == {1: False, 2: False, 3: True}  # the Pod of 'Regional' is left intact


def test_delete_where_deep_removes_only_the_children_of_the_matched_parent(
    session: SnakeSession,
) -> None:
    """A `delete_where` filtering by the PARENT 'Regional' deletes ONLY its Pod (rowcount 1)."""
    affected = session.delete_where(SnakeQuery(Pod).filter(Pod.hub.name == "Regional"))
    assert affected == 1
    remaining = sorted(pod.id for pod in session.all(SnakeQuery(Pod)))
    assert remaining == [1, 2]


def test_update_where_deep_with_composite_pk_updates_the_right_lots(
    session: SnakeSession,
) -> None:
    """With a COMPOSITE PK, filtering by sector 'Alpha' increments ONLY its 2 lots (rowcount 2)."""
    affected = session.update_where(
        SnakeQuery(Lot).filter(Lot.sector.name == "Alpha"),
        [(Lot.weight, Lot.weight + 100)],
    )
    assert affected == 2
    weights = {
        (lot.region, lot.code): lot.weight for lot in session.all(SnakeQuery(Lot))
    }
    assert weights == {("North", 1): 110, ("North", 2): 120, ("South", 1): 5}
