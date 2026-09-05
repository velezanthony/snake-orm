"""INTEGRATION: `raw()`, `refresh()` and `get_or_create()` against a real Postgres.

The three of them only prove something with a database in front: `refresh` exists precisely to pick
up what the DB changed on its own, and `get_or_create` to tell the insertion apart from the match.
Testing them with doubles would be testing the double.

It skips gracefully if there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import (
    PostgresDialect,
    PsycopgDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeRow,
    SnakeSession,
    snake_int,
    snake_model,
    snake_row,
    snake_str,
    snake_table,
)
from snakeorm.core.exceptions import SnakeEmitError, SnakeRegistryError
from snakeorm.migration import emit_create_table
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="se_people")
class Person(SnakeModel):
    """Person with a counter the DB can touch on its own."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    email: SnakeColumn[str] = snake_str(unique=True)
    visits: SnakeColumn[int] = snake_int(default=0)


@snake_row
class Bucket(SnakeRow):
    """Declared shape for the result of the raw SQL."""

    label: str
    total: int


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """Real session with the table created by the ORM's own DDL."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    driver.execute("DROP TABLE IF EXISTS se_people", ())
    driver.execute(emit_create_table(snake_table(Person), PostgresDialect()), ())
    driver.commit()
    try:
        yield SnakeSession(driver, PostgresDialect())
    finally:
        driver.execute("DROP TABLE IF EXISTS se_people", ())
        driver.commit()
        driver.close()


def test_refresh_picks_up_what_the_database_changed(session: SnakeSession) -> None:
    """THE REASON refresh EXISTS: the DB changed the row and the in-memory object never found out.

    Here a bulk write simulates it, but it is the same thing a trigger or a server default would
    do. Without `refresh`, the only way out was to query again and end up with TWO objects for the
    same row.
    """
    person = session.add(Person(id=1, email="a@x.com", visits=0))
    session.commit()

    session._driver.execute("UPDATE se_people SET visits = 7 WHERE id = 1", ())  # noqa: SLF001
    session.commit()
    assert person.visits == 0, "the in-memory object does not know it yet"

    session.refresh(person)
    assert person.visits == 7


def test_refresh_returns_the_same_object(session: SnakeSession) -> None:
    """Checks that it refreshes IN PLACE and does not return a new object: otherwise it would solve nothing."""
    person = session.add(Person(id=1, email="a@x.com", visits=0))
    session.commit()
    assert session.refresh(person) is person


def test_refreshing_a_deleted_row_says_so(session: SnakeSession) -> None:
    """Checks that if the row is gone it is said CLEARLY, instead of passing stale data off as fresh."""
    person = session.add(Person(id=1, email="a@x.com", visits=0))
    session.commit()
    session.delete(person)
    session.commit()

    with pytest.raises(
        SnakeRegistryError, match="could not be refreshed: its row is gone"
    ):
        session.refresh(person)


def test_get_or_create_reports_whether_it_created(session: SnakeSession) -> None:
    """THE piece of data that justifies the method: the boolean tells the insertion from the match."""
    first, created = session.get_or_create(
        SnakeQuery(Person).filter(Person.email == "a@x.com"),
        lambda: Person(id=1, email="a@x.com", visits=0),
    )
    session.commit()
    assert created is True

    again, created_again = session.get_or_create(
        SnakeQuery(Person).filter(Person.email == "a@x.com"),
        lambda: Person(id=2, email="a@x.com", visits=0),
    )
    assert created_again is False
    assert again.id == first.id
    assert session.count(SnakeQuery(Person)) == 1, (
        "it must not have inserted a second row"
    )


def test_raw_hydrates_into_a_declared_shape(session: SnakeSession) -> None:
    """Checks the escape hatch: raw SQL goes in, a TYPED shape comes out, with the values parameterized."""
    session.add_all(
        [
            Person(id=1, email="a@x.com", visits=5),
            Person(id=2, email="b@x.com", visits=15),
        ]
    )
    session.commit()

    rows = session.raw(
        "SELECT email, visits FROM se_people WHERE visits > %s ORDER BY visits",
        (10,),
        into=Bucket,
    )

    assert len(rows) == 1
    assert rows[0].label == "b@x.com"
    assert rows[0].total == 15


def test_raw_complains_when_the_shape_does_not_match(session: SnakeSession) -> None:
    """Checks that a column mismatch fails CLEARLY: the mapping is positional and you declare it."""
    session.add(Person(id=1, email="a@x.com", visits=1))
    session.commit()

    # Against the SINGLE message of `plan_raw`, which the two sessions now share. Pinning the text
    # that only the sync one had was what let the drift live on.
    with pytest.raises(SnakeEmitError, match="the mapping is positional"):
        session.raw("SELECT email FROM se_people", (), into=Bucket)


def test_an_empty_result_cannot_be_checked(session: SnakeSession) -> None:
    """Writes the LIMIT down: the shape is checked row by row, so with no rows it is not checked.

    A query that returns nothing passes even if its shape does not match the `@snake_row`. It is not
    an oversight: with no rows there is nothing to contrast against, and the driver only hands over
    data, not the cursor description. It is documented instead of faking a guarantee that does not
    exist.
    """
    assert session.raw("SELECT email FROM se_people", (), into=Bucket) == []
