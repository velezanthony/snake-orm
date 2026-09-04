"""INTEGRATION: the decorated driver behaves EXACTLY like the real driver.

This is the test that makes the whole of Phase 3 worth something: if wrapping the driver changed
the behaviour, the seam would be useless and the core would have to be touched. Here a full session
—create, insert, read, filter, update— runs through the decorator against a real Postgres.

Skipped gracefully when there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import (
    LoggingDriver,
    PostgresDialect,
    PsycopgDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.migration import emit_create_table
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="log_widgets")
class Widget(SnakeModel):
    """Minimal model for exercising the session through the decorator."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    stock: SnakeColumn[int] = snake_int()


@pytest.fixture
def logged() -> Iterator[tuple[SnakeSession, list[str]]]:
    """A real session whose driver is wrapped by `LoggingDriver`, plus the captured log."""
    import psycopg2

    try:
        raw = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    lines: list[str] = []
    driver = LoggingDriver(raw, write=lines.append)
    driver.execute("DROP TABLE IF EXISTS log_widgets", ())
    driver.execute(emit_create_table(snake_table(Widget), PostgresDialect()), ())
    driver.commit()
    lines.clear()
    try:
        yield SnakeSession(driver, PostgresDialect()), lines
    finally:
        driver.execute("DROP TABLE IF EXISTS log_widgets", ())
        driver.commit()
        driver.close()


def test_a_full_session_works_through_the_decorator(
    logged: tuple[SnakeSession, list[str]],
) -> None:
    """Checks that inserting, reading, filtering and updating work the same through the wrapper."""
    session, _ = logged

    session.add(Widget(id=1, name="tuerca", stock=10))
    session.add(Widget(id=2, name="screw", stock=0))
    session.commit()

    assert session.count(SnakeQuery(Widget)) == 2

    in_stock = session.all(SnakeQuery(Widget).filter(Widget.stock > 0))
    assert [widget.name for widget in in_stock] == ["tuerca"]

    found = session.first(SnakeQuery(Widget).filter(Widget.id == 2))
    assert found is not None
    found.stock = 5
    session.update(found)
    session.commit()

    refreshed = session.first(SnakeQuery(Widget).filter(Widget.id == 2))
    assert refreshed is not None and refreshed.stock == 5


def test_the_log_shows_the_real_sql_and_its_parameters(
    logged: tuple[SnakeSession, list[str]],
) -> None:
    """Checks what gets logged is the real SQL against a real engine, and that the VALUES are not.

    This asserted `'tuerca'` in the line, which is exactly the leak: `write=print` puts that on the
    process stdout, and in a container the stdout is the log aggregator. Over a real `add(User(...))`
    the same line carries the email and the password hash.

    What you debug with is the statement, and the statement is safe by construction — the ORM never
    interpolates, so nothing of the user's is inside it. The values are opt-in, named by position.
    """
    session, lines = logged

    session.add(Widget(id=1, name="tuerca", stock=10))
    session.commit()

    insert = next(line for line in lines if line.startswith("INSERT"))
    assert 'INSERT INTO "public"."log_widgets"' in insert
    assert "'tuerca'" not in insert, (
        "the value went out to the log without being asked for"
    )
    assert "hidden>" in insert
    assert "COMMIT" in lines


def test_the_transaction_boundaries_appear_in_order(
    logged: tuple[SnakeSession, list[str]],
) -> None:
    """Checks the rollback shows up too: a log without the transaction boundaries misleads."""
    session, lines = logged

    session.add(Widget(id=1, name="tuerca", stock=10))
    session.rollback()

    assert "ROLLBACK" in lines
    assert session.count(SnakeQuery(Widget)) == 0
