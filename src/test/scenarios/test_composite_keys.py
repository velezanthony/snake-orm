"""COMPOSITE PK and FK end to end against a real Postgres: the heart of Phase 3.

The domain has a `Province` with a composite PK `(region, code)` and a `Town` with a composite FK
towards it (`province_region, province_code`) plus its `snake_to_many`. The seed is picked so that
NO single column discriminates: `(North, 1)` and `(North, 2)` share `region`; `(North, 1)` and
`(South, 1)` share `code`. That way, if the matching were done by a single column (JOIN, EXISTS or
select-in), the children would get crossed over and the test would catch it.

Checks E2E: (1) the composite to-one JOIN filters correctly; (2) `.include()` of the to-many with a
composite FK loads the right children into each parent (this is what used to be blocked); (3)
`.any()` over the composite relationship works; (4) parents with no children get an empty list.

Against a real Postgres: the SQL is actually executed.
"""

from __future__ import annotations

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.drivers.psycopg import PsycopgDriver
from snakeorm.fields import (
    SnakeColumn,
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


@snake_model(table="kv_provinces")
class Province(SnakeModel):
    """Province with a COMPOSITE PK (region, code) and an inverse to-many towards its towns."""

    region: SnakeColumn[str] = snake_str(primary_key=True)
    code: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    towns: SnakeToMany[Town] = snake_to_many("province")


@snake_model(table="kv_towns")
class Town(SnakeModel):
    """Town with a COMPOSITE FK towards the province (province_region, province_code)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    province_region: SnakeColumn[str] = snake_str()
    province_code: SnakeColumn[int] = snake_int()
    name: SnakeColumn[str] = snake_str()
    province: SnakeToOne[Province] = snake_to_one(province_region, province_code)


_DDL = (
    "DROP TABLE IF EXISTS kv_towns, kv_provinces CASCADE",
    "CREATE TABLE kv_provinces ("
    " region TEXT NOT NULL, code INTEGER NOT NULL, name TEXT NOT NULL,"
    " PRIMARY KEY (region, code))",
    "CREATE TABLE kv_towns ("
    " id INTEGER PRIMARY KEY,"
    " province_region TEXT NOT NULL, province_code INTEGER NOT NULL, name TEXT NOT NULL,"
    " FOREIGN KEY (province_region, province_code)"
    " REFERENCES kv_provinces(region, code))",
)

# (North,1)=Northland has Alpha and Beta; (North,2)=Highland has Gamma; (South,1)=Southland none.
_SEED = (
    "INSERT INTO kv_provinces VALUES"
    " ('North', 1, 'Northland'), ('North', 2, 'Highland'), ('South', 1, 'Southland')",
    "INSERT INTO kv_towns VALUES"
    " (1, 'North', 1, 'Alpha'), (2, 'North', 1, 'Beta'), (3, 'North', 2, 'Gamma')",
)


@pytest.fixture(scope="module")
def session() -> SnakeSession:
    """Creates the composite schema, seeds it and returns a session against the real Postgres."""
    try:
        connection = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    snake_link()
    driver = PsycopgDriver(connection)
    for statement in (*_DDL, *_SEED):
        driver.execute(statement, ())
    driver.commit()
    return SnakeSession(driver, PostgresDialect())


def test_composite_to_one_join_filters_by_the_whole_key(session: SnakeSession) -> None:
    """The composite to-one JOIN ANDs the two pairs: filtering by 'Northland' gives ONLY (North, 1).

    Alpha and Beta hang off (North, 1); Gamma off (North, 2)='Highland'. If the JOIN matched only by
    'region', Gamma (also 'North') would sneak in. The AND of both pairs prevents it.
    """
    towns = session.all(
        SnakeQuery(Town)
        .filter(Town.province.name == "Northland")
        .order_by(Town.name.asc())
    )
    assert [town.name for town in towns] == ["Alpha", "Beta"]


def test_include_to_many_loads_the_right_children_per_parent(
    session: SnakeSession,
) -> None:
    """`.include(Province.towns)` with a composite FK hooks the right children onto each parent.

    This is what used to be BLOCKED. (North, 1)→[Alpha, Beta], (North, 2)→[Gamma], (South, 1)→[].
    No single column discriminates, so only a select-in by TUPLE gives this distribution.
    """
    provinces = session.all(SnakeQuery(Province).include(Province.towns))
    by_key = {(province.region, province.code): province for province in provinces}

    assert sorted(town.name for town in by_key[("North", 1)].towns) == ["Alpha", "Beta"]
    assert sorted(town.name for town in by_key[("North", 2)].towns) == ["Gamma"]


def test_childless_parent_gets_an_empty_list(session: SnakeSession) -> None:
    """The parent with no children (South, 1) gets an EMPTY list, not an unloaded relationship."""
    provinces = session.all(SnakeQuery(Province).include(Province.towns))
    by_key = {(province.region, province.code): province for province in provinces}
    assert by_key[("South", 1)].towns == []


def test_any_over_composite_relation(session: SnakeSession) -> None:
    """`.any(Town.name == 'Gamma')` over the composite relationship returns ONLY (North, 2).

    The EXISTS correlates by BOTH pairs. Gamma lives solely in (North, 2).
    """
    provinces = session.all(
        SnakeQuery(Province).filter(Province.towns.any(Town.name == "Gamma"))
    )
    assert [(province.region, province.code) for province in provinces] == [
        ("North", 2)
    ]


def test_any_without_condition_means_has_at_least_one_town(
    session: SnakeSession,
) -> None:
    """`.any()` with no condition: provinces with at least one town. (South, 1) has none, it drops out."""
    provinces = session.all(
        SnakeQuery(Province)
        .filter(Province.towns.any())
        .order_by(Province.region.asc(), Province.code.asc())
    )
    assert [(province.region, province.code) for province in provinces] == [
        ("North", 1),
        ("North", 2),
    ]
