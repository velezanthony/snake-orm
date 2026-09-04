"""Integration: `server_default` lets the DATABASE put the value in.

`session.add(obj)` WITHOUT passing `created_at` or `public_id` leaves the in-memory object WITH the
timestamp the server put in and WITH the uuid Postgres generated (the wide RETURNING brings them
back). And the DDL the migrations generate (`emit_create_table`) creates the column with its
DEFAULT: that is checked by looking at `information_schema.columns.column_default`.

Its own schema with UNIQUE names so as not to clash with the global registry the tests share.
Against a real Postgres: the SQL is actually executed.
"""

from __future__ import annotations

from snakeorm import SnakeUtc, snake_datetimetz

import uuid
from collections.abc import Iterator
from datetime import datetime

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model, snake_table
from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver
from snakeorm.fields import SnakeColumn, snake_auto, snake_column, snake_str

from snakeorm.metadata import SnakeServerDefault
from snakeorm.migration import emit_create_table
from snakeorm.model import SnakeModel
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="sd_events")
class SdEvent(SnakeModel):
    """Event with two columns the SERVER fills in: timestamp and uuid."""

    id: SnakeColumn[int] = snake_auto()
    label: SnakeColumn[str] = snake_str()
    # `NOW` → CURRENT_TIMESTAMP; `UUID_V4` → gen_random_uuid(): the translation lives in the dialect.
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )
    public_id: SnakeColumn[uuid.UUID] = snake_column(
        server_default=SnakeServerDefault.UUID_V4
    )


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Creates the sd_events table with the DDL generated from the metadata (migrations)."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    dialect = PostgresDialect()
    table = snake_table(SdEvent)
    driver.execute("DROP TABLE IF EXISTS sd_events CASCADE", ())
    driver.execute(
        emit_create_table(table, dialect), ()
    )  # migration DDL, NOTHING by hand
    driver.commit()
    try:
        yield SnakeSession(driver, dialect)
    finally:
        driver.execute("DROP TABLE IF EXISTS sd_events CASCADE", ())
        driver.commit()
        driver.close()


def test_add_fills_server_timestamp_and_uuid(session: SnakeSession) -> None:
    """`add()` without created_at/public_id leaves the object WITH the server's timestamp and uuid."""
    # Plain `now()` (WITH zone): the column is TIMESTAMPTZ, so the value the server returns is
    # aware and comparing it against a naive one (`now()::timestamp`) would be a TypeError.
    before = session._driver.fetch_all("SELECT now()", ())[0][0]  # noqa: SLF001
    assert isinstance(before, datetime)

    event = SdEvent(label="lanzamiento")
    session.add(event)
    session.commit()

    assert isinstance(event.created_at, datetime)
    assert event.created_at >= before
    assert isinstance(event.public_id, uuid.UUID)  # gen_random_uuid(), coerced str→UUID


def test_ddl_creates_columns_with_their_default(session: SnakeSession) -> None:
    """The migrations' DDL creates the columns with their DEFAULT (information_schema)."""
    rows = session._driver.fetch_all(  # noqa: SLF001 - catalog inspection
        "SELECT column_name, column_default FROM information_schema.columns "
        "WHERE table_name = %s",
        ("sd_events",),
    )
    defaults = {name: default for name, default in rows}
    created_default = defaults["created_at"]
    public_default = defaults["public_id"]
    assert isinstance(
        created_default, str
    )  # column_default is text; None when there is no DEFAULT
    assert "CURRENT_TIMESTAMP" in created_default
    assert isinstance(public_default, str)
    assert "gen_random_uuid()" in public_default


def test_two_events_get_distinct_server_uuids(session: SnakeSession) -> None:
    """Each row gets a different uuid from the server: the DB generates it per row, not the client."""
    first = SdEvent(label="a")
    second = SdEvent(label="b")
    session.add(first)
    session.add(second)
    session.commit()
    assert first.public_id != second.public_id
