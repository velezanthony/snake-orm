"""Integration: `upsert()` resolves the conflict with ON CONFLICT against a real Postgres.

Table with `UNIQUE(email)`. Insert; "inserting" the same email again with `update=(...)`
UPDATES the existing row; with `update=()` (DO NOTHING) it touches nothing and does not blow up. In
no case is the row duplicated. The VALUES in the DB are checked, not just that it does not raise.

Against a real Postgres: the SQL is actually executed.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(prefix="up")
class Contact(SnakeModel):
    """Contact with a UNIQUE email: the conflict key of the upsert."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    email: SnakeColumn[str] = snake_str(unique=True)
    name: SnakeColumn[str] = snake_str()


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Session against a real Postgres with the up_contacts table (email UNIQUE) empty."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    driver.execute("DROP TABLE IF EXISTS up_contacts", ())
    driver.execute(
        "CREATE TABLE up_contacts ("
        " id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL)",
        (),
    )
    driver.commit()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.execute("DROP TABLE IF EXISTS up_contacts", ())
        driver.commit()
        driver.close()


def _rows(session: SnakeSession) -> list[Contact]:
    """Reads every row of the table to inspect the values in the DB."""
    return session.all(SnakeQuery(Contact).order_by(Contact.id.asc()))


def test_upsert_inserts_when_no_conflict(session: SnakeSession) -> None:
    """Checks that the first upsert inserts the row as normal."""
    session.upsert(
        Contact(id=1, email="a@x.com", name="Ana"), on_conflict=[Contact.email]
    )
    session.commit()
    rows = _rows(session)
    assert [(c.id, c.email, c.name) for c in rows] == [(1, "a@x.com", "Ana")]


def test_upsert_do_update_overwrites_the_existing_row(session: SnakeSession) -> None:
    """Checks that an email conflict with `update` rewrites the row and does NOT duplicate."""
    session.upsert(
        Contact(id=1, email="a@x.com", name="Ana"), on_conflict=[Contact.email]
    )
    session.commit()
    session.upsert(
        Contact(id=2, email="a@x.com", name="Ana Corregida"),
        on_conflict=[Contact.email],
        update=[Contact.name],
    )
    session.commit()
    rows = _rows(session)
    # A single row: the original (id=1) with the updated name; the id does NOT change (not in update).
    assert [(c.id, c.email, c.name) for c in rows] == [(1, "a@x.com", "Ana Corregida")]


def test_upsert_do_nothing_leaves_the_row_untouched(session: SnakeSession) -> None:
    """Checks that a conflict with `update=()` (DO NOTHING) does not touch the row and does not raise."""
    session.upsert(
        Contact(id=1, email="a@x.com", name="Ana"), on_conflict=[Contact.email]
    )
    session.commit()
    session.upsert(
        Contact(id=2, email="a@x.com", name="Ignorada"), on_conflict=[Contact.email]
    )
    session.commit()
    rows = _rows(session)
    assert [(c.id, c.email, c.name) for c in rows] == [(1, "a@x.com", "Ana")]


def test_upsert_do_update_returns_the_stored_row_to_the_instance(
    session: SnakeSession,
) -> None:
    """Checks that after a DO UPDATE the instance reflects the real row (existing id, via RETURNING)."""
    session.upsert(
        Contact(id=1, email="a@x.com", name="Ana"), on_conflict=[Contact.email]
    )
    session.commit()
    incoming = Contact(id=2, email="a@x.com", name="Ana Corregida")
    session.upsert(incoming, on_conflict=[Contact.email], update=[Contact.name])
    session.commit()
    assert (incoming.id, incoming.name) == (1, "Ana Corregida")


def test_upsert_distinct_email_inserts_a_second_row(session: SnakeSession) -> None:
    """Checks that a different email does not collide: a second row is inserted."""
    session.upsert(
        Contact(id=1, email="a@x.com", name="Ana"), on_conflict=[Contact.email]
    )
    session.upsert(
        Contact(id=2, email="b@x.com", name="Bob"), on_conflict=[Contact.email]
    )
    session.commit()
    rows = _rows(session)
    assert [(c.id, c.email) for c in rows] == [(1, "a@x.com"), (2, "b@x.com")]
