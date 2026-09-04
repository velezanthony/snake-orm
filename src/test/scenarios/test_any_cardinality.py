"""`.any()` does NOT multiply rows. That is the entire reason it exists, so it has to be proven.

The `deep_domain` seed has one maker per nation, and with that data a JOIN would not duplicate
either: a test against that domain would pass even if the EXISTS were wrong. Here an OWN domain
is seeded where a realm has SEVERAL makers matching the filter. That way the difference between
`EXISTS` (one row per parent) and `JOIN` (one row per child) is observable.

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


@snake_model(table="realms")
class Realm(SnakeModel):
    """Realm. One of them will have SEVERAL forges with the same name."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    forges: SnakeToMany[Forge] = snake_to_many("realm")


@snake_model(table="forges")
class Forge(SnakeModel):
    """Forge belonging to a realm."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    realm_id: SnakeColumn[int] = snake_int()
    realm: SnakeToOne[Realm] = snake_to_one(realm_id)


_DDL = (
    "DROP TABLE IF EXISTS forges, realms CASCADE",
    "CREATE TABLE realms (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE forges ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
    " realm_id INTEGER NOT NULL REFERENCES realms(id))",
)

# Nornia has THREE 'Acero' forges; Sudmark none; Kethra has no forges at all.
_SEED = (
    "INSERT INTO realms VALUES (1, 'Nornia'), (2, 'Sudmark'), (3, 'Kethra')",
    "INSERT INTO forges VALUES"
    " (1, 'Acero', 1), (2, 'Acero', 1), (3, 'Acero', 1), (4, 'Bronce', 2)",
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


def test_any_returns_one_row_per_parent(session: SnakeSession) -> None:
    """Nornia has THREE 'Acero' forges and still shows up ONE single time: EXISTS does not multiply."""
    realms = session.all(
        SnakeQuery(Realm).filter(Realm.forges.any(Forge.name == "Acero"))
    )
    assert [realm.name for realm in realms] == ["Nornia"]


def test_a_join_would_have_duplicated(session: SnakeSession) -> None:
    """Proof that the data DOES tell them apart: the equivalent JOIN returns Nornia three times.

    The SQL a JOIN would produce is emitted by hand, to put on record what `.any()` avoids.
    If this test returned a single row, the test above would prove nothing.
    """
    rows = session._driver.fetch_all(  # noqa: SLF001 - deliberate check of the raw SQL
        'SELECT r."name" FROM realms AS r '
        'JOIN forges AS f ON f."realm_id" = r."id" WHERE f."name" = %s',
        ("Acero",),
    )
    assert [row[0] for row in rows] == ["Nornia", "Nornia", "Nornia"]


def test_negated_any_returns_the_complement(session: SnakeSession) -> None:
    """`~any(...)` returns the realms WITHOUT any 'Acero' forge, including those that have none."""
    realms = session.all(
        SnakeQuery(Realm)
        .filter(~Realm.forges.any(Forge.name == "Acero"))
        .order_by(Realm.name.asc())
    )
    assert [realm.name for realm in realms] == ["Kethra", "Sudmark"]


def test_any_without_condition_means_has_at_least_one(session: SnakeSession) -> None:
    """`.any()` with no condition: realms with at least one forge. Kethra has none."""
    realms = session.all(
        SnakeQuery(Realm).filter(Realm.forges.any()).order_by(Realm.name.asc())
    )
    assert [realm.name for realm in realms] == ["Nornia", "Sudmark"]


def test_count_compares_against_the_child_cardinality(session: SnakeSession) -> None:
    """`.count() > 2` resolves as a correlated scalar subquery: only Nornia (3)."""
    realms = session.all(SnakeQuery(Realm).filter(Realm.forges.count() > 2))
    assert [realm.name for realm in realms] == ["Nornia"]


def test_count_zero_finds_childless_parents(session: SnakeSession) -> None:
    """`.count() == 0` finds the childless parents: Kethra."""
    realms = session.all(SnakeQuery(Realm).filter(Realm.forges.count() == 0))
    assert [realm.name for realm in realms] == ["Kethra"]
