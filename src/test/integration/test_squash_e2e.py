"""Squash against a real Postgres: the two scenarios that genuinely matter.

The unit tests check what the runner DECIDES with a double driver. This checks that the decision
is the right one against the engine, and above all the case that justifies the whole mechanism: a
database that already has the history applied receives the squash and does NOT break.

Without `replaces`, that deployment would die with `DuplicateTable` — and it would be the first
anyone hears of it, in production.

Skips gracefully if there is no Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm import PostgresDialect, PsycopgDriver
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import (
    AddColumn,
    CreateTable,
    Migration,
    MigrationRunner,
    squash,
)
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_ID = SnakeColumnInfo(name="id", python_type=int)
_EMAIL = SnakeColumnInfo(name="email", python_type=str)
_NICKNAME = SnakeColumnInfo(name="apodo", python_type=str, nullable=True)


def _table(*columns: SnakeColumnInfo) -> SnakeTableInfo:
    """Table `sq_users` with the given columns."""
    return SnakeTableInfo(
        name="sq_users",
        columns=(_ID, *columns),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    )


def _history() -> list[Migration]:
    """Two migrations: create the table and add a column to it."""
    return [
        Migration("sq0001_inicial", (CreateTable(_table(_EMAIL)),)),
        Migration("sq0002_apodo", (AddColumn(_table(_EMAIL, _NICKNAME), _NICKNAME),)),
    ]


@pytest.fixture
def environment() -> Iterator[tuple[MigrationRunner, PsycopgDriver]]:
    """Runner over a database wiped clean of this scenario."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    def clean() -> None:
        driver.execute("DROP TABLE IF EXISTS sq_users CASCADE", ())
        driver.execute("DELETE FROM snake_migrations WHERE version LIKE %s", ("sq%",))
        driver.commit()

    runner = MigrationRunner(driver, PostgresDialect())
    runner.ensure_tracking_table()
    clean()
    try:
        yield runner, driver
    finally:
        clean()
        driver.close()


def _columns(driver: PsycopgDriver) -> list[str]:
    """The real columns of the table, read from the catalogue."""
    rows = driver.fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'sq_users' ORDER BY ordinal_position",
        (),
    )
    return [str(row[0]) for row in rows]


def test_an_already_migrated_database_survives_the_squash(
    environment: tuple[MigrationRunner, PsycopgDriver],
) -> None:
    """THE case that justifies the mechanism: the DB is already migrated and the squash arrives.

    Without `replaces`, the squash would attempt a `CREATE TABLE` over a table that exists and the
    deployment would die with `DuplicateTable`. With it, it is marked applied without running
    anything and the table stays EXACTLY as it was — which is what has to be checked, not merely
    that nothing blew up.
    """
    runner, driver = environment
    history = _history()
    runner.apply(history)
    before = _columns(driver)

    new = runner.apply([*history, squash(history, version="sq0003_squash")])

    assert new == ["sq0003_squash"], "only the squash is recorded"
    assert _columns(driver) == before, "the table is not touched"
    assert "sq0003_squash" in runner.applied_versions()


def test_a_fresh_database_gets_the_final_state_in_one_step(
    environment: tuple[MigrationRunner, PsycopgDriver],
) -> None:
    """Fresh install: the squash builds the final state directly, without walking the steps."""
    runner, driver = environment
    history = _history()

    runner.apply([*history, squash(history, version="sq0003_squash")])

    assert _columns(driver) == ["id", "email", "apodo"]
    assert runner.applied_versions() >= {"sq0003_squash"}
    assert "sq0001_inicial" not in runner.applied_versions(), (
        "the replaced ones are not applied"
    )


def test_a_half_applied_database_is_refused(
    environment: tuple[MigrationRunner, PsycopgDriver],
) -> None:
    """With the history HALF APPLIED it stops, and the database is left untouched.

    What matters is not only that it raises: it is that it does NOT leave the table half-modified.
    It is checked that the column still pending is still missing.
    """
    from snakeorm.core.exceptions import SnakeMigrationError

    runner, driver = environment
    history = _history()
    runner.apply(history[:1])  # only the first one

    with pytest.raises(
        SnakeMigrationError, match="replaces a history that was applied HALF-WAY"
    ):
        runner.apply([*history, squash(history, version="sq0003_squash")])

    assert _columns(driver) == ["id", "email"], "the DB is not touched when it stops"
