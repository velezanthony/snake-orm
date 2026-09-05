"""The CLI runs on the engine the APPLICATION declares, not on the one it was hardcoded to.

`SnakeOrmConfig.migrate()` has been multi-engine from the day it was written — its docstring says so
out loud, and says what it is contrasting itself with: *"unlike the CLI, which is tied to Postgres"*.
So a project on SQLite or MySQL had two ways to apply a migration and only one of them worked, and
the one that did not was the one the documentation tells you to run.

The pairing itself was never the problem: `SnakeConnectionConfig.driver_and_dialect()` builds driver
and dialect together, by `backend`, so they cannot be mismatched. The CLI simply was not asking.
"""

from __future__ import annotations

import argparse

import pytest

from snakeorm.cli.app import _connection_for
from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.contrib.config import SnakeOrmConfig
from snakeorm.dialects import PostgresDialect, SQLiteDialect
from snakeorm.drivers import SQLiteDriver


def _args(dsn: str | None = None, database: str = "default") -> argparse.Namespace:
    """The two attributes `_connection_for` reads off the parsed arguments."""
    return argparse.Namespace(dsn=dsn, database=database)


def test_a_sqlite_project_gets_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    """A config declaring SQLite yields the SQLite driver AND its dialect, paired."""
    config = SnakeOrmConfig(
        databases={
            "default": SnakeConnectionConfig(
                backend=SnakeBackend.SQLITE, name=":memory:"
            )
        }
    )
    monkeypatch.setattr("snakeorm.cli.app.find_config", lambda: config)

    driver, dialect = _connection_for(_args())

    assert isinstance(driver, SQLiteDriver)
    assert isinstance(dialect, SQLiteDialect)
    driver.close()


def test_an_explicit_dsn_still_means_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--dsn` keeps its old meaning: a Postgres DSN, and no application is consulted.

    The override has to stay, and it has to stay Postgres-shaped: a project with no
    `SnakeOrmConfig` at all —a script, a one-off— is exactly who passes a DSN by hand, and that
    path worked before this change. What must not happen is the app being ignored when it IS there.
    """
    seen: list[str] = []

    def _connect(dsn: str) -> object:
        seen.append(dsn)
        return object()

    monkeypatch.setattr(
        "snakeorm.cli.app.PsycopgDriver",
        type("_Fake", (), {"connect": staticmethod(_connect)}),
    )
    monkeypatch.setattr(
        "snakeorm.cli.app.find_config",
        lambda: pytest.fail("the app must not be consulted when --dsn is explicit"),
    )

    _, dialect = _connection_for(_args(dsn="postgresql://x/y"))

    assert isinstance(dialect, PostgresDialect)
    assert seen == ["postgresql://x/y"]
