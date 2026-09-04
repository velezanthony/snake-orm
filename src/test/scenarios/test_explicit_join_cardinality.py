"""`.join()` to a collection DOES multiply rows. That is exactly what sets it apart from `.any()`.

`.any()` returns ONE row per parent (existence); `.join()` returns ONE row per CHILD (the child's
rows, flat). With a parent that has SEVERAL children the difference is observable, so here we seed
an OWN domain (unique table names) where that shows: an INNER multiplies and excludes the parent
with no children; a LEFT includes that parent with the child's columns as NULL.

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
from snakeorm.query import SnakeJoin, SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="guilds")
class Guild(SnakeModel):
    """Guild. One will have SEVERAL smiths, another one, another NONE."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    smiths: SnakeToMany[Smith] = snake_to_many("guild")


@snake_model(table="smiths")
class Smith(SnakeModel):
    """Herrero perteneciente a un gremio."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    guild_id: SnakeColumn[int] = snake_int()
    guild: SnakeToOne[Guild] = snake_to_one(guild_id)


_DDL = (
    "DROP TABLE IF EXISTS smiths, guilds CASCADE",
    "CREATE TABLE guilds (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE smiths ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
    " guild_id INTEGER NOT NULL REFERENCES guilds(id))",
)

# Ironhold has THREE smiths; Stormpeak one; Hollow none.
_SEED = (
    "INSERT INTO guilds VALUES (1, 'Ironhold'), (2, 'Stormpeak'), (3, 'Hollow')",
    "INSERT INTO smiths VALUES"
    " (1, 'Bruk', 1), (2, 'Dara', 1), (3, 'Ferro', 1), (4, 'Sol', 2)",
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


def test_inner_join_multiplies_one_row_per_child(session: SnakeSession) -> None:
    """Checks that an INNER join returns ONE row per child: Ironhold shows up 3 times, Hollow 0.

    This is the difference with `.any()` (which would give a single row per parent): here the child's
    data comes out flat and multiplied. The parent with no smiths (Hollow) does NOT appear.
    """
    joined = SnakeQuery(Guild).join(Guild.smiths)
    joined = joined.order_by(Guild.name.asc(), joined.right.name.asc())
    rows = session.select(joined, Guild.name, joined.right.name)
    assert rows == [
        ("Ironhold", "Bruk"),
        ("Ironhold", "Dara"),
        ("Ironhold", "Ferro"),
        ("Stormpeak", "Sol"),
    ]


def test_left_join_includes_the_childless_parent_with_null(
    session: SnakeSession,
) -> None:
    """Checks that a LEFT join includes the parent WITHOUT children (Hollow) with the child column NULL."""
    joined = SnakeQuery(Guild).join(Guild.smiths, how=SnakeJoin.LEFT)
    joined = joined.order_by(Guild.name.asc())
    rows = session.select(joined, Guild.name, joined.right.name)
    # Hollow has no smiths: it shows up once with the child name as None (the LEFT JOIN NULL).
    assert ("Hollow", None) in rows
    # Ironhold still multiplies (3 smiths); Stormpeak shows up with its single smith.
    ironhold_rows = [row for row in rows if row[0] == "Ironhold"]
    assert len(ironhold_rows) == 3
    assert ("Stormpeak", "Sol") in rows
