"""Integration: deep navigation (JOINs) against a REAL Postgres.

The jewel of the project, checked end to end: `Truck.maker.nation.name == "España"` type-checks,
generates the JOINs and returns the right rows from the devcontainer's Postgres. Skipped if there
is no DB. Seeded graph: España→SEAT→Ibiza, Alemania→BMW→M3.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver
from snakeorm.fields import SnakeRelationshipNotLoaded
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn
from test.scenarios.deep_domain import Maker, Nation, Truck, create_schema, seed

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def deep_session() -> Iterator[SnakeSession]:
    """Session against the real Postgres with the deep domain seeded and linked."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    create_schema(driver)
    seed(driver)
    driver.commit()
    snake_link()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.close()


def test_deep_filter_spain(deep_session: SnakeSession) -> None:
    """Checks the deep filter: trucks whose maker is from España → Ibiza (SEAT)."""
    trucks = deep_session.all(
        SnakeQuery(Truck).filter(Truck.maker.nation.name == "España")
    )
    assert [t.model for t in trucks] == ["Ibiza"]


def test_deep_filter_germany(deep_session: SnakeSession) -> None:
    """Checks the other branch: maker from Alemania → M3 (BMW)."""
    trucks = deep_session.all(
        SnakeQuery(Truck).filter(Truck.maker.nation.name == "Alemania")
    )
    assert [t.model for t in trucks] == ["M3"]


def test_one_level_relation_filter(deep_session: SnakeSession) -> None:
    """Checks a single-level JOIN: maker SEAT → Ibiza."""
    trucks = deep_session.all(SnakeQuery(Truck).filter(Truck.maker.name == "SEAT"))
    assert [t.model for t in trucks] == ["Ibiza"]


def test_include_loads_to_one_relation(deep_session: SnakeSession) -> None:
    """Checks that .include() loads the to-one relationship: truck.maker reachable in a single SELECT."""
    truck = deep_session.first(
        SnakeQuery(Truck).filter(Truck.model == "Ibiza").include(Truck.maker)
    )
    assert truck is not None
    assert truck.maker.name == "SEAT"


def test_include_deep_chain_loads_nested(deep_session: SnakeSession) -> None:
    """Checks a chained include: .include(Truck.maker.nation) loads maker AND nation, nested."""
    truck = deep_session.first(
        SnakeQuery(Truck).filter(Truck.model == "M3").include(Truck.maker.nation)
    )
    assert truck is not None
    assert truck.maker.name == "BMW"
    assert truck.maker.nation.name == "Alemania"


def test_relation_not_loaded_raises_against_real_pg(deep_session: SnakeSession) -> None:
    """Checks the anti-N+1 lock: without .include(), reaching the relationship blows up (fires no query)."""
    truck = deep_session.first(SnakeQuery(Truck).filter(Truck.model == "Ibiza"))
    assert truck is not None
    with pytest.raises(SnakeRelationshipNotLoaded, match="Relation 'maker' was not"):
        _ = truck.maker


def test_include_to_many_loads_list(deep_session: SnakeSession) -> None:
    """Checks that .include() loads a to-many relationship via select-in: nation.makers → list."""
    nation = deep_session.first(
        SnakeQuery(Nation).filter(Nation.name == "España").include(Nation.makers)
    )
    assert nation is not None
    assert [maker.name for maker in nation.makers] == ["SEAT"]


def test_include_to_many_over_many_parents(deep_session: SnakeSession) -> None:
    """Checks the select-in over several parents: each nation with its list (a single child query)."""
    nations = deep_session.all(SnakeQuery(Nation).include(Nation.makers))
    by_name = {n.name: sorted(m.name for m in n.makers) for n in nations}
    assert by_name == {"España": ["SEAT"], "Alemania": ["BMW"]}


def test_to_many_not_loaded_raises_against_real_pg(deep_session: SnakeSession) -> None:
    """Checks the anti-N+1 lock on to-many against a real Postgres."""
    nation = deep_session.first(SnakeQuery(Nation).filter(Nation.name == "España"))
    assert nation is not None
    with pytest.raises(SnakeRelationshipNotLoaded, match="Relation 'makers' was not"):
        _ = nation.makers


def test_any_returns_nations_with_matching_makers(deep_session: SnakeSession) -> None:
    """Checks that `.any(cond)` runs the real EXISTS: only España has a 'SEAT' maker."""
    nations = deep_session.all(
        SnakeQuery(Nation).filter(Nation.makers.any(Maker.name == "SEAT"))
    )
    assert [nation.name for nation in nations] == ["España"]


def test_negated_any_returns_the_complement(deep_session: SnakeSession) -> None:
    """Checks that `~.any(cond)` returns the complement: the nation WITHOUT a 'SEAT' maker."""
    nations = deep_session.all(
        SnakeQuery(Nation).filter(~Nation.makers.any(Maker.name == "SEAT"))
    )
    assert [nation.name for nation in nations] == ["Alemania"]


def test_any_without_condition_has_no_duplicate_rows(
    deep_session: SnakeSession,
) -> None:
    """Checks that `.any()` (EXISTS) returns one row per parent, with no duplication (it is not a JOIN)."""
    nations = deep_session.all(SnakeQuery(Nation).filter(Nation.makers.any()))
    names = [nation.name for nation in nations]
    assert sorted(names) == ["Alemania", "España"]
    assert len(names) == len(
        set(names)
    )  # EXISTS does not multiply rows the way a JOIN would
