"""annotate() against a real Postgres: the VALUES of the counts are checked, not just that it runs.

Just like `test_any_cardinality`, an OWN domain is seeded with UNIQUE table names. Parents are
seeded with a different number of children (3, 1 and 0) so the real cardinality can be observed.

DECISION about childless parents: annotate() counts the children with a CORRELATED SCALAR SUBQUERY
(`AnnRealm.forges.count()`), not with a JOIN. A scalar subquery returns 0 for a parent with no
children, so the parent DOES appear, with count 0. That is the expected semantics (you want ALL the
rows of the base model with their count, zeros included), equivalent to a LEFT JOIN but without the
risk of a COUNT(*) counting the LEFT JOIN's NULL row as 1. It also avoids building inverted JOIN
support for to-many (which the type graph forbids navigating). The SELECT groups by the base model's
PK, as annotate() requires.
"""

from __future__ import annotations

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import SnakeResult, snake_model, snake_result
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


@snake_model(table="annotate_int_realms")
class AnnRealm(SnakeModel):
    """Realm with a variable number of forges (0, 1 or 3)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    forges: SnakeToMany[AnnForge] = snake_to_many("realm")


@snake_model(table="annotate_int_forges")
class AnnForge(SnakeModel):
    """Forge belonging to a realm."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    realm_id: SnakeColumn[int] = snake_int()
    realm: SnakeToOne[AnnRealm] = snake_to_one(realm_id)


@snake_result
class RealmForgeCount(SnakeResult[AnnRealm]):
    """The realm row annotated with how many forges it has."""

    realm: AnnRealm
    forge_count: int


_DDL = (
    "DROP TABLE IF EXISTS annotate_int_forges, annotate_int_realms CASCADE",
    "CREATE TABLE annotate_int_realms (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE annotate_int_forges ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
    " realm_id INTEGER NOT NULL REFERENCES annotate_int_realms(id))",
)

# Nornia has 3 forges; Sudmark 1; Kethra 0.
_SEED = (
    "INSERT INTO annotate_int_realms VALUES (1, 'Nornia'), (2, 'Sudmark'), (3, 'Kethra')",
    "INSERT INTO annotate_int_forges VALUES"
    " (1, 'Acero', 1), (2, 'Bronce', 1), (3, 'Hierro', 1), (4, 'Plata', 2)",
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


def test_annotate_counts_children_per_parent(session: SnakeSession) -> None:
    """Each realm comes out with its REAL number of forges: Nornia 3, Sudmark 1, Kethra 0."""
    stats = session.annotate(
        SnakeQuery(AnnRealm).order_by(AnnRealm.name.asc()),
        RealmForgeCount,
        forge_count=AnnRealm.forges.count(),
    )
    by_name = {stat.realm.name: stat.forge_count for stat in stats}
    assert by_name == {"Nornia": 3, "Sudmark": 1, "Kethra": 0}


def test_childless_parent_appears_with_zero(session: SnakeSession) -> None:
    """Documented DECISION: the childless parent (Kethra) DOES appear, with count 0 (not omitted)."""
    stats = session.annotate(
        SnakeQuery(AnnRealm), RealmForgeCount, forge_count=AnnRealm.forges.count()
    )
    kethra = next(stat for stat in stats if stat.realm.name == "Kethra")
    assert kethra.forge_count == 0


def test_hydrated_base_row_is_a_real_model(session: SnakeSession) -> None:
    """The hydrated base row is a real instance of the model, with its columns populated."""
    stats = session.annotate(
        SnakeQuery(AnnRealm).filter(AnnRealm.name == "Nornia"),
        RealmForgeCount,
        forge_count=AnnRealm.forges.count(),
    )
    assert isinstance(stats[0].realm, AnnRealm)
    assert stats[0].realm.name == "Nornia"


def test_escape_hatch_reads_the_annotation_on_the_hydrated_object(
    session: SnakeSession,
) -> None:
    """The escape hatch `realm.aggregate.forge_count` reads the aggregate off the hydrated object."""
    stats = session.annotate(
        SnakeQuery(AnnRealm).filter(AnnRealm.name == "Nornia"),
        RealmForgeCount,
        forge_count=AnnRealm.forges.count(),
    )
    assert stats[0].realm.aggregate.forge_count == 3
