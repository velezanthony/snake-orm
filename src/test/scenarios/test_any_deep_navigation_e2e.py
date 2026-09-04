"""`.any()` that NAVIGATES two levels inside the EXISTS, against a real Postgres.

Grandparent→parent→child chain: `Dominion` → `Cohort` → `Recruit`. The query is over the COHORTS and
the filter `Cohort.recruits.any(Recruit.cohort.dominion.name == "Alianza")` navigates TWO to-one
relationships INSIDE the EXISTS (`Recruit.cohort` → `Cohort`, `.dominion` → `Dominion`). Since
`recruit.cohort` is the cohort itself, the question amounts to "cohorts of the 'Alianza' dominion
that have at least one recruit".

The seed is picked so that the EXISTS shows: 'Rojo' (Alianza) has THREE recruits and must still come
out ONCE (EXISTS does not multiply); 'Verde' (Alianza) has no recruits and drops out; 'Azul'
(Horda) drops out because of the dominion. The complement with `~` picks up exactly the excluded ones.

UNCOMMON model and table names: they do not clash with other tests in the global registry (the
resolution of relationships by model name demands it). Against a real Postgres: the SQL is executed.
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


@snake_model(table="dnav_dominions")
class Dominion(SnakeModel):
    """Dominion (grandparent) with an inverse to-many towards its cohorts."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    cohorts: SnakeToMany[Cohort] = snake_to_many("dominion")


@snake_model(table="dnav_cohorts")
class Cohort(SnakeModel):
    """Cohort (parent): belongs to a dominion and groups recruits."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    dominion_id: SnakeColumn[int] = snake_int()
    dominion: SnakeToOne[Dominion] = snake_to_one(dominion_id)
    recruits: SnakeToMany[Recruit] = snake_to_many("cohort")


@snake_model(table="dnav_recruits")
class Recruit(SnakeModel):
    """Recruit (child): belongs to a cohort. Recruit→Cohort→Dominion chain."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    cohort_id: SnakeColumn[int] = snake_int()
    cohort: SnakeToOne[Cohort] = snake_to_one(cohort_id)


_DDL = (
    "DROP TABLE IF EXISTS dnav_recruits, dnav_cohorts, dnav_dominions CASCADE",
    "CREATE TABLE dnav_dominions (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE dnav_cohorts ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
    " dominion_id INTEGER NOT NULL REFERENCES dnav_dominions(id))",
    "CREATE TABLE dnav_recruits ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
    " cohort_id INTEGER NOT NULL REFERENCES dnav_cohorts(id))",
)

# Alianza (1): 'Rojo' (10, THREE recruits) and 'Verde' (11, none). Horda (2): 'Azul' (12, one).
_SEED = (
    "INSERT INTO dnav_dominions VALUES (1, 'Alianza'), (2, 'Horda')",
    "INSERT INTO dnav_cohorts VALUES (10, 'Rojo', 1), (11, 'Verde', 1), (12, 'Azul', 2)",
    "INSERT INTO dnav_recruits VALUES"
    " (100, 'Ana', 10), (101, 'Bob', 10), (102, 'Cid', 10), (103, 'Dan', 12)",
)


@pytest.fixture(scope="module")
def session() -> SnakeSession:
    """Creates the schema, seeds it and returns a session against the real Postgres."""
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


def test_two_level_navigation_inside_exists_yields_one_row_per_parent(
    session: SnakeSession,
) -> None:
    """'Rojo' has THREE recruits and still shows up ONCE: the EXISTS with a double JOIN does not multiply.

    The filter navigates `Recruit.cohort.dominion.name` (two to-one hops) inside the EXISTS; only the
    cohorts of the 'Alianza' dominion WITH at least one recruit match. 'Verde' (Alianza, no recruits)
    and 'Azul' (Horda) drop out.
    """
    cohorts = session.all(
        SnakeQuery(Cohort)
        .filter(Cohort.recruits.any(Recruit.cohort.dominion.name == "Alianza"))
        .order_by(Cohort.name.asc())
    )
    assert [cohort.name for cohort in cohorts] == ["Rojo"]


def test_negated_two_level_navigation_returns_the_complement(
    session: SnakeSession,
) -> None:
    """`~any(...)` returns the cohorts WITHOUT that recruit: 'Azul' (Horda) and 'Verde' (no recruits)."""
    cohorts = session.all(
        SnakeQuery(Cohort)
        .filter(~Cohort.recruits.any(Recruit.cohort.dominion.name == "Alianza"))
        .order_by(Cohort.name.asc())
    )
    assert [cohort.name for cohort in cohorts] == ["Azul", "Verde"]
