"""NESTED include (SnakePrefetch) against a real Postgres: grandparent→children→grandchildren, one query per LEVEL.

The seed has a grandparent with SEVERAL children and several grandchildren, PLUS a child with no
grandchildren and a grandparent with no children: that way we observe that each parent with no
descendants gets an empty list without breaking the chain, and that the number of queries is the
number of LEVELS (3), not one per parent (N+1). The real driver is wrapped in one that COUNTS the
`fetch_all` calls. Its own schema with unique table names (`prefetch_*`) so as not to collide in the
global registry.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.drivers.psycopg import PsycopgDriver
from snakeorm.fields import (
    SnakeColumn,
    SnakePrefetch,
    SnakeRelationshipNotLoaded,
    SnakeToMany,
    SnakeToOne,
    snake_int,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.linker.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="prefetch_continents")
class PfContinent(SnakeModel):
    """Grandparent: one with several children, another with none."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    regions: SnakeToMany[PfRegion] = snake_to_many("continent")


@snake_model(table="prefetch_regions")
class PfRegion(SnakeModel):
    """Child: belongs to a continent; one of them will have no grandchildren."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    continent_id: SnakeColumn[int] = snake_int()
    continent: SnakeToOne[PfContinent] = snake_to_one(continent_id)
    colonies: SnakeToMany[PfColony] = snake_to_many("region")


@snake_model(table="prefetch_colonies")
class PfColony(SnakeModel):
    """Grandchild: belongs to a region."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    region_id: SnakeColumn[int] = snake_int()
    region: SnakeToOne[PfRegion] = snake_to_one(region_id)


_DDL = (
    "DROP TABLE IF EXISTS prefetch_colonies, prefetch_regions, prefetch_continents CASCADE",
    "CREATE TABLE prefetch_continents (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE prefetch_regions ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
    " continent_id INTEGER NOT NULL REFERENCES prefetch_continents(id))",
    "CREATE TABLE prefetch_colonies ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
    " region_id INTEGER NOT NULL REFERENCES prefetch_regions(id))",
)

# Eurasia(1) has THREE regions: Iberia and Nordics with colonies, Sahel with NONE.
# Oceania(2) has NO regions (a grandparent with no children).
_SEED = (
    "INSERT INTO prefetch_continents VALUES (1, 'Eurasia'), (2, 'Oceania')",
    "INSERT INTO prefetch_regions VALUES"
    " (1, 'Iberia', 1), (2, 'Nordics', 1), (3, 'Sahel', 1)",
    "INSERT INTO prefetch_colonies VALUES"
    " (1, 'Toledo', 1), (2, 'Lisbon', 1), (3, 'Oslo', 2)",
)


class _CountingDriver:
    """Wraps the real driver and COUNTS the `fetch_all` calls (to prove one query per level)."""

    def __init__(self, inner: PsycopgDriver) -> None:
        self._inner = inner
        self.fetch_count = 0

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.fetch_count += 1
        return self._inner.fetch_all(sql, params)

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields whatever
        `fetch_all` returns. The degradation is written HERE, in plain sight, not done by the framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        return self._inner.execute(sql, params)

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:
        self._inner.commit()

    def rollback(self) -> None:
        self._inner.rollback()

    def savepoint(self, name: str) -> None:  # pragma: no cover
        self._inner.savepoint(name)

    def release_savepoint(self, name: str) -> None:  # pragma: no cover
        self._inner.release_savepoint(name)

    def rollback_to_savepoint(self, name: str) -> None:  # pragma: no cover
        self._inner.rollback_to_savepoint(name)

    def close(self) -> None:  # pragma: no cover
        self._inner.close()


@pytest.fixture(scope="module")
def session() -> SnakeSession:
    """Creates the schema, seeds it and returns a session with the driver that counts the queries."""
    try:
        connection = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    snake_link()
    real = PsycopgDriver(connection)
    for statement in (*_DDL, *_SEED):
        real.execute(statement, ())
    real.commit()
    return SnakeSession(_CountingDriver(real), PostgresDialect())


def _counter(session: SnakeSession) -> _CountingDriver:
    """Retrieves the counting driver from the session (it is its injected driver)."""
    driver = session._driver  # noqa: SLF001 - deliberate inspection of the query count
    assert isinstance(driver, _CountingDriver)
    return driver


def test_nested_prefetch_loads_the_full_graph(session: SnakeSession) -> None:
    """Checks the loaded VALUES: each continent with its regions and each region with its colonies."""
    continents = session.all(
        SnakeQuery(PfContinent).include(
            SnakePrefetch(PfContinent.regions).then(PfRegion.colonies)
        )
    )
    by_name = {continent.name: continent for continent in continents}

    eurasia = by_name["Eurasia"]
    regions = {region.name: region for region in eurasia.regions}
    assert sorted(regions) == ["Iberia", "Nordics", "Sahel"]
    assert sorted(colony.name for colony in regions["Iberia"].colonies) == [
        "Lisbon",
        "Toledo",
    ]
    assert [colony.name for colony in regions["Nordics"].colonies] == ["Oslo"]
    assert regions["Sahel"].colonies == []  # a child with no grandchildren: empty list

    assert (
        by_name["Oceania"].regions == []
    )  # a grandparent with no children: empty list


def test_nested_prefetch_emits_one_query_per_level(session: SnakeSession) -> None:
    """Checks that 3 queries are emitted (root + regions + colonies), NOT one per parent (anti N+1)."""
    counter = _counter(session)
    counter.fetch_count = 0
    session.all(
        SnakeQuery(PfContinent).include(
            SnakePrefetch(PfContinent.regions).then(PfRegion.colonies)
        )
    )
    assert counter.fetch_count == 3


def test_relation_not_included_still_raises(session: SnakeSession) -> None:
    """Checks that touching a relationship NOT included still fires SnakeRelationshipNotLoaded (the anti-N+1 lock).

    It prefetches continent→regions→colonies, but NOT `region.continent` (the to-one back): touching it
    on a loaded region must blow up, not resolve a silent N+1.
    """
    continents = session.all(
        SnakeQuery(PfContinent).include(
            SnakePrefetch(PfContinent.regions).then(PfRegion.colonies)
        )
    )
    region = next(r for c in continents for r in c.regions)
    with pytest.raises(
        SnakeRelationshipNotLoaded, match="Relation 'continent' was not"
    ):
        _ = region.continent
