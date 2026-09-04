"""Opening the SAME schema on the THREE engines at once, for tests whose subject is the comparison.

A cross-engine agreement is only worth what the engines behind it are worth: checked over two, it
reads like a law and is a coincidence. `test_compound_nesting_matrix.py` grew its own copy of this
and found three bugs with it; every file that wants the same shape was going to copy it again, and a
copy is where the third engine gets quietly dropped.

The harness SEEDS nothing: what a row has to say differs per test, and seeding here would push every
file towards the same rows — which is how a set-operation test ends up with data where a regrouping
is invisible.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager

import pytest

from snakeorm import (
    AsyncPsycopgDriver,
    AsyncPyMySQLDriver,
    AsyncSession,
    AsyncSQLiteDriver,
    MySQLDialect,
    PostgresDialect,
    PsycopgDriver,
    PyMySQLDriver,
    SQLiteDialect,
    SQLiteDriver,
    SnakeSession,
)
from snakeorm.dialects import SnakeDialect
from snakeorm.drivers.asyncbase import AsyncDriver
from snakeorm.drivers.base import SnakeDriver
from snakeorm.migration import emit_create_table
from snakeorm.registry import registry
from test.conftest import NO_MYSQL_REASON, NO_SERVER_REASON
from test.scenarios.db import dsn

# How each engine spells "drop it if it is there". SQLite gets a fresh in-memory file per run, so it
# has nothing to drop.
_DROP = {
    "sqlite": None,
    "postgres": "DROP TABLE IF EXISTS %s CASCADE",
    "mysql": "DROP TABLE IF EXISTS %s",
}


def mysql_kwargs() -> dict[str, object]:
    """The MySQL connection, from the variables the rest of the suite already reads."""
    host = os.environ.get("MYSQL_HOST")
    if not host:  # pragma: no cover - environment
        pytest.skip(f"{NO_MYSQL_REASON}: MYSQL_HOST is not set")
    return {
        "host": host,
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
        "database": os.environ.get("MYSQL_DB", "snakeorm_db"),
    }


def table_names(models: Sequence[type]) -> list[str]:
    """The table names of these models, in declaration order."""
    names = []
    for model in models:
        table = registry.table_of(model)
        assert table is not None
        names.append(table.name)
    return names


def create_tables(
    driver: SnakeDriver, dialect: SnakeDialect, models: Sequence[type], drop: str | None
) -> None:
    """Drops (where there is something to drop) and creates these models' tables on this engine."""
    for model in models:
        table = registry.table_of(model)
        assert table is not None
        if drop is not None:
            driver.execute(drop % table.name, ())
        driver.execute(emit_create_table(table, dialect), ())
    driver.commit()


def drop_tables(driver: SnakeDriver, names: Sequence[str], drop: str) -> None:
    """Drops these tables in REVERSE order, so a foreign key never holds the parent."""
    for name in reversed(list(names)):
        driver.execute(drop % name, ())
    driver.commit()


@contextmanager
def three_drivers(
    models: Sequence[type], sqlite_path: str = ":memory:"
) -> Iterator[dict[str, SnakeDriver]]:
    """The three SYNCHRONOUS drivers with these models' tables already created.

    A missing engine SKIPS with the phrase `conftest.py` recognises, so the strict switches turn it
    into the failure it is in CI.

    `sqlite_path` is there for the tests that open a SECOND connection to the same SQLite: an
    in-memory database belongs to the connection that created it, so a test comparing two sessions
    over one database has to be handed a file.
    """
    import psycopg2
    import pymysql

    sqlite_driver = SQLiteDriver.connect(sqlite_path)
    try:
        postgres_driver = PsycopgDriver.connect(dsn())
    except psycopg2.OperationalError as error:  # pragma: no cover - environment
        sqlite_driver.close()
        pytest.skip(f"{NO_SERVER_REASON}: {error}")
    kwargs = mysql_kwargs()
    try:
        mysql_driver = PyMySQLDriver.connect(**kwargs)  # type: ignore[arg-type]
    except pymysql.err.OperationalError as error:  # pragma: no cover - environment
        sqlite_driver.close()
        postgres_driver.close()
        pytest.skip(f"{NO_MYSQL_REASON}: {error}")

    drivers: dict[str, SnakeDriver] = {
        "sqlite": sqlite_driver,
        "postgres": postgres_driver,
        "mysql": mysql_driver,
    }
    for name, driver in drivers.items():
        create_tables(driver, DIALECTS[name], models, _DROP[name])
    try:
        yield drivers
    finally:
        names = table_names(models)
        for name, driver in drivers.items():
            drop = _DROP[name]
            if drop is not None:
                drop_tables(driver, names, drop)
            driver.close()


DIALECTS: dict[str, SnakeDialect] = {
    "sqlite": SQLiteDialect(),
    "postgres": PostgresDialect(),
    "mysql": MySQLDialect(),
}
"""The dialect of each engine, by the SAME key the sessions are handed back under."""


@contextmanager
def three_sessions(
    models: Sequence[type],
    sqlite_path: str = ":memory:",
    *,
    wrap: Callable[[str, SnakeDriver], SnakeDriver] | None = None,
) -> Iterator[dict[str, SnakeSession]]:
    """A synchronous session per engine, with the tables created. The caller seeds them.

    `wrap` dresses each driver before the session gets it — a `LoggingDriver` to count statements, a
    `TimeoutDriver`, a pool. It receives the ENGINE NAME as well as the driver, and that is not
    decoration: `TimeoutDriver` REFUSES to wrap SQLite, so a caller who wants a timeout has to be
    able to tell the three apart. Without the name every such test would go back to opening its own
    three connections by hand, which is what this module exists to stop.
    """
    with three_drivers(models, sqlite_path) as drivers:
        yield {
            name: SnakeSession(
                driver if wrap is None else wrap(name, driver), DIALECTS[name]
            )
            for name, driver in drivers.items()
        }


# -- The asynchronous twin -------------------------------------------------------------------------
#
# It did not exist, so `_open_async` got copied by hand into `test_compound_async_parity.py` and
# `test_async_mysql_e2e.py` — and a copy is where the third engine gets quietly dropped, which is
# the reason the synchronous half of this file exists.


async def create_tables_async(
    driver: AsyncDriver, dialect: SnakeDialect, models: Sequence[type], drop: str | None
) -> None:
    """The async twin of `create_tables`. The async drivers do their OWN DDL.

    Not reusing the synchronous ones for setup, because an in-memory SQLite belongs to the
    connection that opened it: the DDL has to travel down the same connection the test will read
    from, or `:memory:` hands back an empty database.
    """
    for model in models:
        table = registry.table_of(model)
        assert table is not None
        if drop is not None:
            await driver.execute(drop % table.name, ())
        await driver.execute(emit_create_table(table, dialect), ())
    await driver.commit()


@asynccontextmanager
async def three_async_drivers(
    models: Sequence[type], sqlite_path: str = ":memory:"
) -> AsyncIterator[dict[str, AsyncDriver]]:
    """The three ASYNCHRONOUS drivers with these models' tables created. Same skips as the sync one."""
    import psycopg
    import pymysql

    sqlite_driver = await AsyncSQLiteDriver.connect(sqlite_path)
    try:
        postgres_driver = await AsyncPsycopgDriver.connect(dsn())
    except psycopg.OperationalError as error:  # pragma: no cover - environment
        await sqlite_driver.close()
        pytest.skip(f"{NO_SERVER_REASON}: {error}")
    kwargs = mysql_kwargs()
    try:
        mysql_driver = await AsyncPyMySQLDriver.connect(**kwargs)  # type: ignore[arg-type]
    except pymysql.err.OperationalError as error:  # pragma: no cover - environment
        await sqlite_driver.close()
        await postgres_driver.close()
        pytest.skip(f"{NO_MYSQL_REASON}: {error}")

    drivers: dict[str, AsyncDriver] = {
        "sqlite": sqlite_driver,
        "postgres": postgres_driver,
        "mysql": mysql_driver,
    }
    for name, driver in drivers.items():
        await create_tables_async(driver, DIALECTS[name], models, _DROP[name])
    try:
        yield drivers
    finally:
        names = table_names(models)
        for name, driver in drivers.items():
            drop = _DROP[name]
            if drop is not None:
                for table_name in reversed(names):
                    await driver.execute(drop % table_name, ())
                await driver.commit()
            await driver.close()


@asynccontextmanager
async def three_async_sessions(
    models: Sequence[type],
    sqlite_path: str = ":memory:",
    *,
    wrap: Callable[[str, AsyncDriver], AsyncDriver] | None = None,
) -> AsyncIterator[dict[str, AsyncSession]]:
    """An asynchronous session per engine, with the tables created. Same `wrap` as the sync twin."""
    async with three_async_drivers(models, sqlite_path) as drivers:
        yield {
            name: AsyncSession(
                driver if wrap is None else wrap(name, driver), DIALECTS[name]
            )
            for name, driver in drivers.items()
        }
