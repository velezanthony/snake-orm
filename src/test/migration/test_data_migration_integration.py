"""Integration: DATA migrations and savepoints against a real Postgres.

Two things are tested for real (SQL executed, values read back from the catalog/tables):

1. A DATA migration (`RunPython`) that fills one column from another using the typed ORM
   (`session.update_where`) in the `forward`: it is applied, the VALUES in the database are
   checked; then a rollback is done and it is checked that the `backward` undid them.
2. A REAL savepoint: inside a transaction, a `session.savepoint()` block that raises leaves what
   was inserted BEFORE the savepoint intact and discards what was inserted INSIDE.

Skipped if there is no Postgres. UNIQUE names (`dm_*`) so as not to clash with other scenarios.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver, SnakeDriver
from snakeorm.fields import SnakeColumn, snake_int

from snakeorm.linker.linker import snake_link
from snakeorm.migration import Migration, MigrationRunner, RunPython
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_VERSION = "dm_data_001"


@snake_model(table="dm_accounts")
class DmAccount(SnakeModel):
    """Account with a balance and a mirror column that a data migration fills in."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    balance: SnakeColumn[int] = snake_int()
    mirror: SnakeColumn[int] = snake_int()


def _dm_forward(session: SnakeSession) -> None:
    """Data migration: copies `balance` into `mirror` for every row (it fills a column in)."""
    session.update_where(
        SnakeQuery(DmAccount).filter(DmAccount.id > 0),
        [(DmAccount.mirror, DmAccount.balance)],
    )


def _dm_backward(session: SnakeSession) -> None:
    """Reverse: puts `mirror` back to 0."""
    session.update_where(
        SnakeQuery(DmAccount).filter(DmAccount.id > 0),
        [(DmAccount.mirror, 0)],
    )


_DDL = (
    "DROP TABLE IF EXISTS dm_accounts CASCADE",
    "CREATE TABLE dm_accounts ("
    " id INTEGER PRIMARY KEY, balance INTEGER NOT NULL, mirror INTEGER NOT NULL DEFAULT 0)",
)


def _cleanup(driver: SnakeDriver) -> None:
    """Leaves the state clean (test table + recorded test version rows)."""
    driver.execute("DROP TABLE IF EXISTS dm_accounts CASCADE", ())
    driver.execute(
        "DELETE FROM public.snake_migrations WHERE version LIKE %s", ("dm_%",)
    )
    driver.commit()


@pytest.fixture
def env() -> Iterator[tuple[MigrationRunner, SnakeSession, SnakeDriver]]:
    """Runner + session + driver against a real Postgres, with `dm_accounts` freshly created."""
    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    snake_link()
    runner = MigrationRunner(driver, PostgresDialect())
    runner.ensure_tracking_table()
    _cleanup(driver)
    for statement in _DDL:
        driver.execute(statement, ())
    driver.commit()
    try:
        yield runner, SnakeSession(driver, PostgresDialect()), driver
    finally:
        _cleanup(driver)
        driver.close()


def _mirrors(driver: SnakeDriver) -> list[tuple[int, int]]:
    """Reads (id, mirror) from every row, ordered by id."""
    rows = driver.fetch_all("SELECT id, mirror FROM dm_accounts ORDER BY id", ())
    return [(cast("int", row[0]), cast("int", row[1])) for row in rows]


def test_data_migration_fills_column_and_rolls_back(
    env: tuple[MigrationRunner, SnakeSession, SnakeDriver],
) -> None:
    """The `forward` fills `mirror` from `balance`; the rollback (backward) puts it back to 0."""
    runner, _session, driver = env
    driver.execute(
        "INSERT INTO dm_accounts (id, balance, mirror) VALUES (1, 100, 0), (2, 250, 0)",
        (),
    )
    driver.commit()

    migration = Migration(_VERSION, (RunPython(_dm_forward, _dm_backward),))
    assert runner.apply([migration]) == [_VERSION]

    # forward: mirror ended up equal to balance in every row
    assert _mirrors(driver) == [(1, 100), (2, 250)]
    assert _VERSION in runner.applied_versions()

    runner.rollback(migration)

    # backward: mirror went back to 0 and the version is no longer on record
    assert _mirrors(driver) == [(1, 0), (2, 0)]
    assert _VERSION not in runner.applied_versions()


def test_savepoint_discards_inner_keeps_outer(
    env: tuple[MigrationRunner, SnakeSession, SnakeDriver],
) -> None:
    """A savepoint that reverts leaves what came BEFORE intact and discards what is INSIDE it."""
    _runner, session, driver = env
    # Row inserted BEFORE the savepoint (it must survive).
    driver.execute(
        "INSERT INTO dm_accounts (id, balance, mirror) VALUES (10, 1, 0)", ()
    )

    with pytest.raises(RuntimeError, match="boom"), session.savepoint():
        # Row inserted INSIDE the savepoint (it must be discarded on revert).
        driver.execute(
            "INSERT INTO dm_accounts (id, balance, mirror) VALUES (11, 2, 0)", ()
        )
        raise RuntimeError("boom")

    driver.commit()
    rows = driver.fetch_all("SELECT id FROM dm_accounts ORDER BY id", ())
    assert [cast("int", row[0]) for row in rows] == [
        10
    ]  # the 11 (savepoint) got reverted
