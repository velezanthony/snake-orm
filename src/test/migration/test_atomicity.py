"""Integration: a migration is ATOMIC on every engine whose DDL is transactional.

A migration whose SECOND operation fails must leave no trace of the first: the runner rolls back and
the database is as it was, with the version unrecorded.

**Two engines run it and the third declares it cannot**, and that third one is the point of the
claim. MySQL answers `Cap.TRANSACTIONAL_DDL: Nope()` — its DDL commits implicitly, so a three-step
migration that fails on the third leaves the first two applied — while SQLite answers `Full()` and
was never being exercised. Atomicity is exactly the promise you cannot check by reading the SQL, and
SQLite is the engine where the promise is least obvious.

Whether the table survived is asked through the ORM's own introspector rather than with catalogue
SQL: `information_schema` does not exist in SQLite, and a hand-written query per engine would be a
second opinion about the schema living inside the test that checks the first one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import psycopg2
import pytest

from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.dialects.base import SnakeDialect
from snakeorm.dialects.capabilities import Cap, Nope
from snakeorm.drivers import PsycopgDriver, SnakeDriver, SQLiteDriver
from snakeorm.introspection import (
    PostgresIntrospector,
    SnakeIntrospector,
    SQLiteIntrospector,
)
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import CreateTable, DropTable, Migration, MigrationRunner
from test.conftest import NO_SERVER_REASON
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration

_VERSION = "test_atom_001"
_TABLE = "atom_alpha"


def _table(name: str) -> SnakeTableInfo:
    """Minimal test table with a single PK column."""
    id_col = SnakeColumnInfo(name="id", python_type=int)
    return SnakeTableInfo(
        name=name, columns=(id_col,), primary_key=SnakePrimaryKeyInfo(columns=(id_col,))
    )


class _Engine:
    """One engine under test: how to reach it, and what it raises when an operation fails."""

    def __init__(
        self,
        driver: SnakeDriver,
        dialect: SnakeDialect,
        introspector: SnakeIntrospector,
        failure: type[Exception],
    ) -> None:
        self.driver = driver
        self.dialect = dialect
        self.introspector = introspector
        self.failure = failure
        self.runner = MigrationRunner(driver, dialect)

    def has_table(self, name: str) -> bool:
        """Asked of the ORM, which knows how each engine spells its catalogue."""
        return any(table.name == name for table in self.introspector.tables())

    def clean(self) -> None:
        """Leave no test table and no test version behind."""
        self.driver.execute(f"DROP TABLE IF EXISTS {_TABLE}", ())
        self.driver.execute(
            f"DELETE FROM snake_migrations WHERE version LIKE {self.dialect.placeholder(1)}",
            ("test_atom_%",),
        )
        self.driver.commit()


@pytest.fixture
def postgres() -> Iterator[_Engine]:
    """A real Postgres, with the tracking table ready and a clean slate."""
    try:
        driver = PsycopgDriver.connect(dsn())
    except psycopg2.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    engine = _Engine(
        driver, PostgresDialect(), PostgresIntrospector(driver), psycopg2.Error
    )
    engine.runner.ensure_tracking_table()
    engine.clean()
    yield engine
    engine.clean()
    driver.close()


@pytest.fixture
def sqlite() -> Iterator[_Engine]:
    """An in-memory SQLite. It answers `Full()` for transactional DDL and nobody was checking."""
    driver = SQLiteDriver.connect(":memory:")
    engine = _Engine(driver, SQLiteDialect(), SQLiteIntrospector(driver), sqlite3.Error)
    engine.runner.ensure_tracking_table()
    engine.clean()
    yield engine
    driver.close()


_ENGINES = ["postgres", "sqlite"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_partial_migration_leaves_no_trace(
    engine: str, request: pytest.FixtureRequest
) -> None:
    """First operation creates a table, second one fails: after the rollback the table is not there."""
    under_test: _Engine = request.getfixturevalue(engine)
    migration = Migration(
        _VERSION,
        (CreateTable(_table(_TABLE)), DropTable(_table("atom_missing"))),
    )

    with pytest.raises(under_test.failure):
        under_test.runner.apply([migration])

    # The aborted transaction has to be cleared before the connection will answer anything else.
    under_test.driver.rollback()

    assert under_test.has_table(_TABLE) is False
    assert _VERSION not in under_test.runner.applied_versions()


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_whole_migration_is_recorded(
    engine: str, request: pytest.FixtureRequest
) -> None:
    """The counter-proof: when every operation succeeds, the table is there and the version is in."""
    under_test: _Engine = request.getfixturevalue(engine)
    migration = Migration(_VERSION, (CreateTable(_table(_TABLE)),))

    assert under_test.runner.apply([migration]) == [_VERSION]
    assert under_test.has_table(_TABLE) is True
    assert _VERSION in under_test.runner.applied_versions()


def test_mysql_says_it_cannot_and_that_is_why_it_is_absent() -> None:
    """MySQL is missing from the run above because it DECLARES its DDL is not transactional.

    Written down so the absence is a decision rather than a gap somebody stopped noticing — and this
    one matters more than most: on MySQL a half-applied migration is the normal outcome of a failure,
    not a bug, and a reader who found the engine simply missing might assume otherwise.
    """
    support = MySQLDialect().capabilities.support_for(Cap.TRANSACTIONAL_DDL)

    assert isinstance(support, Nope), (
        f"MySQL now answers {type(support).__name__} for transactional DDL: add it to _ENGINES"
    )
    assert "commits implicitly" in support.reason
