"""Scalar aggregates over a collection, against a real Postgres: sum_/avg/min_/max_/count.

Each one emits a correlated scalar subquery over a numeric column OF THE CHILD. Here we check that
the VALUES the DB returns are the right ones, by filtering with them. An OWN domain is seeded
(UNIQUE table names) with parents of different cardinality, including one WITHOUT children.

Documented and verified over zero rows (a childless parent):
    - `COUNT(*)` of zero rows is 0 (not NULL).
    - `SUM/AVG/MIN/MAX` of zero rows are NULL (not 0): there is no row to aggregate.
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


@snake_model(table="covens")
class Coven(SnakeModel):
    """Coven (parent). Its sorcerers contribute a numeric column (`mana`) to aggregate."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    sorcerers: SnakeToMany[Sorcerer] = snake_to_many("coven")


@snake_model(table="sorcerers")
class Sorcerer(SnakeModel):
    """Sorcerer (child), with its `mana` level and the FK to its coven."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    mana: SnakeColumn[int] = snake_int()
    coven_id: SnakeColumn[int] = snake_int()
    coven: SnakeToOne[Coven] = snake_to_one(coven_id)


_DDL = (
    "DROP TABLE IF EXISTS sorcerers, covens CASCADE",
    "CREATE TABLE covens (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE sorcerers ("
    " id INTEGER PRIMARY KEY, mana INTEGER NOT NULL,"
    " coven_id INTEGER NOT NULL REFERENCES covens(id))",
)

# Aurora: mana 10/20/30 (count 3, sum 60, avg 20, min 10, max 30).
# Boreal: mana 5 (count 1, sum/avg/min/max 5).
# Cinder: NO sorcerers (count 0; sum/avg/min/max NULL).
_SEED = (
    "INSERT INTO covens VALUES (1, 'Aurora'), (2, 'Boreal'), (3, 'Cinder')",
    "INSERT INTO sorcerers VALUES (1, 10, 1), (2, 20, 1), (3, 30, 1), (4, 5, 2)",
)


@pytest.fixture(scope="module")
def session() -> SnakeSession:
    """Creates its own schema, seeds it and returns a session against the real Postgres."""
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


def test_sum_filters_by_child_total(session: SnakeSession) -> None:
    """`.sum_(mana) > 50`: only Aurora (60). Boreal (5) drops out; Cinder (NULL) does too."""
    covens = session.all(
        SnakeQuery(Coven).filter(Coven.sorcerers.sum_(Sorcerer.mana) > 50)
    )
    assert [coven.name for coven in covens] == ["Aurora"]


def test_avg_filters_by_child_average(session: SnakeSession) -> None:
    """`.avg(mana) > 10.0`: only Aurora (20). Boreal (5) out; Cinder (NULL) out."""
    covens = session.all(
        SnakeQuery(Coven).filter(Coven.sorcerers.avg(Sorcerer.mana) > 10.0)
    )
    assert [coven.name for coven in covens] == ["Aurora"]


def test_min_filters_by_child_minimum(session: SnakeSession) -> None:
    """`.min_(mana) == 5`: only Boreal (its single sorcerer has mana 5)."""
    covens = session.all(
        SnakeQuery(Coven).filter(Coven.sorcerers.min_(Sorcerer.mana) == 5)
    )
    assert [coven.name for coven in covens] == ["Boreal"]


def test_max_filters_by_child_maximum(session: SnakeSession) -> None:
    """`.max_(mana) == 30`: only Aurora (its strongest sorcerer has mana 30)."""
    covens = session.all(
        SnakeQuery(Coven).filter(Coven.sorcerers.max_(Sorcerer.mana) == 30)
    )
    assert [coven.name for coven in covens] == ["Aurora"]


def test_aggregate_values_of_a_populated_parent(session: SnakeSession) -> None:
    """Aurora's raw VALUES: count 3, sum 60, min 10, max 30 (all integers)."""
    rows = session.select(
        SnakeQuery(Coven).filter(Coven.name == "Aurora"),
        Coven.sorcerers.count(),
        Coven.sorcerers.sum_(Sorcerer.mana),
        Coven.sorcerers.min_(Sorcerer.mana),
        Coven.sorcerers.max_(Sorcerer.mana),
    )
    assert rows == [(3, 60, 10, 30)]


def test_childless_parent_counts_zero_but_sums_null(session: SnakeSession) -> None:
    """Parent WITHOUT children (Cinder): `COUNT(*)` is 0; `SUM` of zero rows is NULL (not 0)."""
    rows = session.select(
        SnakeQuery(Coven).filter(Coven.name == "Cinder"),
        Coven.sorcerers.count(),
        Coven.sorcerers.sum_(Sorcerer.mana),
    )
    assert rows == [(0, None)]
