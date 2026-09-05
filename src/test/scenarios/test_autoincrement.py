"""Integration: autoincrement PK against a REAL Postgres.

`Note(text="...")` with no id → the DDL creates the SERIAL column, the INSERT omits the id (the
model leaves it unset), and the RETURNING gives back the generated id and assigns it to the
instance. The DDL is generated from the metadata (dogfooding emit_create_table). Skipped if
there is no DB.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model, snake_table
from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver
from snakeorm.fields import SnakeColumn, snake_auto, snake_str

from snakeorm.migration import emit_create_table
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(prefix="ai")
class Note(SnakeModel):
    """Note with an autoincrement PK."""

    id: SnakeColumn[int] = snake_auto()
    text: SnakeColumn[str] = snake_str()


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Session against a real Postgres with the ai_notes table created from the metadata."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    driver.execute("DROP TABLE IF EXISTS ai_notes", ())
    driver.execute(emit_create_table(snake_table(Note), PostgresDialect()), ())
    driver.commit()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.execute("DROP TABLE IF EXISTS ai_notes", ())
        driver.commit()
        driver.close()


def test_add_without_id_generates_it(session: SnakeSession) -> None:
    """Checks that inserting without an id makes the DB generate it and RETURNING assign it."""
    note = Note(text="hola")
    session.add(note)
    session.commit()
    assert isinstance(note.id, int)
    assert note.id >= 1


def test_two_inserts_get_distinct_ids(session: SnakeSession) -> None:
    """Checks that two insertions receive distinct autoincrement ids."""
    first = session.add(Note(text="a"))
    second = session.add(Note(text="b"))
    session.commit()
    assert first.id != second.id
    assert {n.text for n in session.all(SnakeQuery(Note))} == {"a", "b"}
