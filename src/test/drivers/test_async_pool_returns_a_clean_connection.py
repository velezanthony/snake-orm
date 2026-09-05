"""The asynchronous twin of `test_pool_returns_a_clean_connection.py`, and it went red as a whole.

`AsyncSnakePool`'s lent driver had NO rollback on any line of the file. Its synchronous sibling has
one, plus a docstring declaring that cleaning up "is the pool's contract and not a courtesy" — so
this is not a gap somebody chose, it is the shape of the sync one copied without its reasons.

What that costs: task A does `await session.insert(...)`, blows up before the commit, its
`finally: await session.close()` puts the connection back in the queue WITH the transaction open and
the INSERT inside it. Task B takes that connection, runs its SELECT inside a stranger's unit of
work, and its own `commit()` confirms the INSERT that A abandoned.

It is not theoretical: the three demos in `frameworks/` use `AsyncSnakePool`, and their `give_back`
(`shared/config.py`) files the connection away and does nothing else. So did the pool the published
guide shows — an `asyncio.Queue` with no rollback anywhere in it. In the synchronous colour the
guarantee was at least being BORROWED from psycopg2's `putconn`; here nothing supplied it at all.

The questions are the sync file's, asked with a `give_back` that adds nothing, because that is the
smallest pool anybody could write and the only one that can tell whose guarantee it is.

`asyncio.run(scenario())` and no plugin, which is how `test_async_pool.py` next door does it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from snakeorm.drivers.asyncbase import AsyncDriver
from snakeorm.drivers.asyncpool import AsyncSnakePool


class _Recorder:
    """An async driver that records the calls the pool makes to it on the way out."""

    def __init__(self, *, rollback_raises: bool = False) -> None:
        self.calls: list[str] = []
        self._rollback_raises = rollback_raises

    async def rollback(self) -> None:
        self.calls.append("rollback")
        if self._rollback_raises:
            raise ConnectionError("connection already closed")

    async def commit(self) -> None:
        self.calls.append("commit")

    async def close(self) -> None:
        self.calls.append("close")

    async def savepoint(self, name: str) -> None: ...
    async def release_savepoint(self, name: str) -> None: ...
    async def rollback_to_savepoint(self, name: str) -> None: ...

    async def execute(self, sql: str, params: object) -> int:
        return 0

    async def fetch_all(self, sql: str, params: object) -> list[tuple[object, ...]]:
        return []

    async def fetch_iter(
        self, sql: str, params: object, *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        empty: tuple[tuple[object, ...], ...] = ()
        for row in empty:
            yield row

    @property
    def last_insert_id(self) -> int:
        return 0


def _pool(inner: _Recorder, returned: list[object]) -> AsyncSnakePool:
    """The smallest pool anybody could write: one connection, a list for a free queue."""

    async def borrow() -> AsyncDriver:
        return inner  # type: ignore[return-value]

    async def give_back(driver: AsyncDriver) -> None:
        returned.append(driver)

    async def close_all() -> None: ...

    return AsyncSnakePool(borrow, give_back, close_all)


def test_the_connection_is_rolled_back_before_it_goes_back() -> None:
    """The contract the synchronous pool keeps and this one did not keep at all.

    Whatever the borrower left open —an uncommitted write, a savepoint it never released— belongs to
    a unit of work that is over, and the next borrower must not be able to see it, commit it by
    accident, or roll its own work back into it.
    """

    async def scenario() -> None:
        inner = _Recorder()
        returned: list[object] = []

        driver = await _pool(inner, returned).acquire()
        await driver.close()

        assert inner.calls == ["rollback"], (
            "the connection went back carrying whatever was open"
        )
        assert returned == [inner]

    asyncio.run(scenario())


def test_a_connection_whose_rollback_fails_is_still_handed_back() -> None:
    """The clean-up may fail; the RETURN may not be skipped because of it.

    The sync twin of this test explains the cost: the backing pool goes on counting the connection
    as lent for ever, and the idempotency guard stops any retry from putting it right.
    """

    async def scenario() -> None:
        inner = _Recorder(rollback_raises=True)
        returned: list[object] = []

        driver = await _pool(inner, returned).acquire()
        with pytest.raises(ConnectionError):
            await driver.close()

        assert returned == [inner], (
            "the connection was lost: the pool will never lend it again"
        )

    asyncio.run(scenario())


def test_returning_twice_still_hands_it_back_only_once() -> None:
    """The idempotency the async pool already had, kept: adding the rollback must not break it.

    A repeated `close()` —the session's plus an outer `finally`— returning the SAME connection twice
    is one of the hardest failures a pool can have to find, because from then on two tasks each
    believe they have their own.
    """

    async def scenario() -> None:
        inner = _Recorder()
        returned: list[object] = []

        driver = await _pool(inner, returned).acquire()
        await driver.close()
        await driver.close()

        assert returned == [inner]
        assert inner.calls == ["rollback"], "the second close cleaned up again too"

    asyncio.run(scenario())
