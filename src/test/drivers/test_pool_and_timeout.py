"""Connection pool and statement timeout, once again without touching the core.

The detail that decides the design of the pool: a driver HOLDS a transaction. So you can NOT borrow
a connection per statement and give it back —the `INSERT` and its `COMMIT` have to travel on the
same one—. The unit that gets lent out is the connection for the whole life of the session, and
`close()` RETURNS it to the pool instead of closing it. Getting this wrong is the classic way for a
pool to corrupt transactions.

The timeout is a CONNECTION setting, not a statement one: it is set once when wrapping and holds for
everything that comes afterwards. Emitting a `SET` before every query would double the traffic for
nothing.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import cast

import pytest

from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import AsyncDriver, SnakeDriver, TimeoutDriver
from snakeorm.drivers.pool import SnakePool


class _FakeDriver:
    """Pretend driver that notes down what it is asked for."""

    def __init__(self, label: str = "c0") -> None:
        self.label = label
        self.statements: list[str] = []
        self.closed = False

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.statements.append(sql)
        return []

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields what `fetch_all`
        returns. The degradation is written HERE, in plain sight, not done by the framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.statements.append(sql)
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:
        self.statements.append("COMMIT")

    def rollback(self) -> None:
        self.statements.append("ROLLBACK")

    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...

    def close(self) -> None:
        self.closed = True


# -- Timeout ---------------------------------------------------------------------------------


def test_the_timeout_is_set_once_when_wrapping() -> None:
    """Verifies that the `statement_timeout` is set ONCE, not before every statement."""
    inner = _FakeDriver()
    driver = TimeoutDriver(inner, PostgresDialect(), statement_timeout_ms=5000)

    driver.execute("SELECT 1", ())
    driver.execute("SELECT 2", ())

    assert inner.statements[0] == "SET statement_timeout = 5000"
    assert inner.statements.count("SET statement_timeout = 5000") == 1


def test_a_timeout_driver_is_still_a_driver() -> None:
    """Verifies the contract: wrapping cannot break the Protocol."""
    assert isinstance(
        TimeoutDriver(_FakeDriver(), PostgresDialect(), statement_timeout_ms=1000),
        SnakeDriver,
    )


def test_a_non_positive_timeout_is_refused() -> None:
    """Verifies that a zero or negative timeout is refused: in Postgres 0 means NO LIMIT AT ALL.

    Accepting it silently would give exactly the opposite of what was asked for.
    """
    with pytest.raises(
        ValueError, match="statement_timeout_ms has to be greater than zero"
    ):
        TimeoutDriver(_FakeDriver(), PostgresDialect(), statement_timeout_ms=0)


# -- Pool ------------------------------------------------------------------------------------


class _FakeBackend:
    """Pretend pool: it hands out drivers and notes down which ones come back."""

    def __init__(self) -> None:
        self.handed: list[_FakeDriver] = []
        self.returned: list[_FakeDriver] = []
        self.closed = False

    def borrow(self) -> _FakeDriver:
        driver = _FakeDriver(label=f"c{len(self.handed)}")
        self.handed.append(driver)
        return driver

    def give_back(self, driver: SnakeDriver) -> None:
        assert isinstance(driver, _FakeDriver)
        self.returned.append(driver)

    def close_all(self) -> None:
        self.closed = True


@pytest.fixture
def backend() -> _FakeBackend:
    """An observable pool backend."""
    return _FakeBackend()


def test_acquire_hands_out_a_usable_driver(backend: _FakeBackend) -> None:
    """Verifies that what is lent out satisfies the Protocol and reaches the real driver."""
    pool = SnakePool(backend.borrow, backend.give_back, backend.close_all)
    driver = pool.acquire()

    assert isinstance(driver, SnakeDriver)
    driver.execute("SELECT 1", ())
    assert backend.handed[0].statements == ["SELECT 1"]


def test_closing_a_borrowed_driver_returns_it_instead_of_closing_it(
    backend: _FakeBackend,
) -> None:
    """THE KEY of the pool: `close()` RETURNS the connection, it does not close it. Or no pool."""
    pool = SnakePool(backend.borrow, backend.give_back, backend.close_all)
    driver = pool.acquire()

    driver.close()

    assert backend.returned == [backend.handed[0]]
    assert backend.handed[0].closed is False


def test_the_whole_transaction_travels_on_one_connection(backend: _FakeBackend) -> None:
    """Verifies that a whole transaction travels on the SAME connection.

    Borrowing per statement would split the INSERT and its COMMIT across two different connections,
    and the transaction would be lost. That is why the unit lent out is the connection, not the
    statement.
    """
    pool = SnakePool(backend.borrow, backend.give_back, backend.close_all)
    driver = pool.acquire()

    driver.execute("INSERT INTO t VALUES (1)", ())
    driver.commit()

    assert len(backend.handed) == 1
    assert backend.handed[0].statements == ["INSERT INTO t VALUES (1)", "COMMIT"]


def test_the_context_manager_returns_the_connection_even_on_error(
    backend: _FakeBackend,
) -> None:
    """Verifies that an exception does not keep the connection: that drains the pool in prod."""
    pool = SnakePool(backend.borrow, backend.give_back, backend.close_all)

    with pytest.raises(RuntimeError):
        with pool.connection():
            raise RuntimeError("something failed halfway through")

    assert len(backend.returned) == 1


def test_closing_the_pool_closes_the_backend(backend: _FakeBackend) -> None:
    """Verifies that closing the pool really does close all of its connections."""
    pool = SnakePool(backend.borrow, backend.give_back, backend.close_all)
    pool.close()
    assert backend.closed is True


def test_the_timeout_asks_the_dialect_instead_of_writing_postgres() -> None:
    """`TimeoutDriver` emits what the ENGINE understands, not `SET statement_timeout` everywhere.

    It wrote that line itself, which is Postgres and only Postgres, under a class name that promises
    nothing about engines. Measured: MySQL answers `1193 Unknown system variable` and SQLite a
    syntax error, so the knob that keeps one hung query from draining the pool worked on one engine
    out of three.
    """
    from snakeorm.dialects import MySQLDialect, PostgresDialect

    postgres = _FakeDriver()
    TimeoutDriver(postgres, PostgresDialect(), statement_timeout_ms=5000)
    assert postgres.statements == ["SET statement_timeout = 5000"]

    mysql = _FakeDriver()
    TimeoutDriver(mysql, MySQLDialect(), statement_timeout_ms=5000)
    assert mysql.statements == ["SET SESSION max_statement_time = 5"]


def test_an_engine_with_no_timeout_is_refused_instead_of_ignored() -> None:
    """On SQLite it STOPS: there is no server-side statement timeout, and pretending is worse.

    Accepting the wrap and doing nothing would hand back a driver that looks capped and is not —
    the caller asked for a limit precisely because they did not want one query to take the pool
    down with it.
    """
    from snakeorm.dialects import SQLiteDialect

    with pytest.raises(SnakeDialectError) as error:
        TimeoutDriver(_FakeDriver(), SQLiteDialect(), statement_timeout_ms=5000)

    assert "SQLiteDialect" in str(error.value)


def test_the_async_twin_kept_the_guard_its_brother_has() -> None:
    """`statement_timeout_ms=0` is refused in async too. It was not, and the reason matters.

    On Postgres `statement_timeout = 0` means NO LIMIT, so accepting a 0 does the exact opposite of
    what was asked. The synchronous driver has refused it from the start, with the reason written
    down; the async one was written afterwards and copied the shape without the guard — the same way
    it copied the Postgres SQL.
    """
    import asyncio

    from snakeorm.dialects import PostgresDialect
    from snakeorm.drivers import AsyncTimeoutDriver

    with pytest.raises(ValueError, match="NO limit"):
        asyncio.run(
            AsyncTimeoutDriver.apply_to(
                cast("AsyncDriver", _FakeAsyncDriver()),
                PostgresDialect(),
                statement_timeout_ms=0,
            )
        )


class _FakeAsyncDriver:
    """The async counterpart of `_FakeDriver`, only as far as the timeout decorator needs it."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        self.statements.append(sql)
        return 0
