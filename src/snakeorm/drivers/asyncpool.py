"""`AsyncSnakePool`: the async mirror of `SnakePool`, with the same three safeguards.

A server with a hundred concurrent tasks opens a hundred connections if nobody hands them out, and a
Postgres connection costs memory on the server even when it is doing nothing.

The three rules are the same as in the synchronous sibling:

- **`pre_ping`** — a failover or a server restart leaves dead connections IN the pool. Without
  checking the pulse, the next request takes one and fails for something that is not its fault.
- **`recycle_seconds`** — many servers cut idle connections on their own. Recycling by age throws
  them away BEFORE the server does, which is the difference between a discard and an error in
  production.
- **`timeout_seconds`** — with the pool drained, `psycopg2` does not block: it raises instantly. The
  timeout is there to WAIT for one to be freed.

And the discard cap, which is not a knob but a fuse: without it, a downed database turns this into
an infinite loop throwing connections away and asking for another —process alive, no errors, no
progress—, a failure no alert ever notices.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from time import monotonic

from snakeorm.core.exceptions import SnakePoolTimeout
from snakeorm.drivers.asyncbase import AsyncDriver

AsyncBorrow = Callable[[], Awaitable[AsyncDriver]]
AsyncGiveBack = Callable[[AsyncDriver], Awaitable[None]]
AsyncCloseAll = Callable[[], Awaitable[None]]
AsyncDiscard = Callable[[AsyncDriver], Awaitable[None]]
Clock = Callable[[], float]

_MAX_DISCARDS = 3
"""Dead connections in a row before giving up on retrying. Three are not bad luck: it is the database."""


class _AsyncPooledDriver:
    """Wraps the lent connection so that `close()` RETURNS it instead of closing it.

    It is the piece that makes the pool work without anybody upstream noticing: an `AsyncSession`
    closes its driver when it is done, as always, and the connection goes back into the queue.
    """

    def __init__(self, inner: AsyncDriver, give_back: AsyncGiveBack) -> None:
        self._inner = inner
        self._give_back = give_back
        self._returned = False

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        """Delegates the read."""
        return await self._inner.fetch_all(sql, params)

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        """Delegates the streaming. NOT an `async def`: it returns the iterator, just like the Protocol."""
        return self._inner.fetch_iter(sql, params, chunk=chunk)

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        """Delegates the write."""
        return await self._inner.execute(sql, params)

    @property
    def last_insert_id(self) -> int:
        """Delegates the id of the last INSERT."""
        return self._inner.last_insert_id

    async def commit(self) -> None:
        """Delegates the commit."""
        await self._inner.commit()

    async def rollback(self) -> None:
        """Delegates the rollback."""
        await self._inner.rollback()

    async def savepoint(self, name: str) -> None:
        """Delegates the savepoint."""
        await self._inner.savepoint(name)

    async def release_savepoint(self, name: str) -> None:
        """Delegates the release."""
        await self._inner.release_savepoint(name)

    async def rollback_to_savepoint(self, name: str) -> None:
        """Delegates the return to the savepoint."""
        await self._inner.rollback_to_savepoint(name)

    async def close(self) -> None:
        """RETURNS the connection to the pool instead of closing it, ROLLED BACK. Idempotent.

        The rollback is the pool's contract and not a courtesy: `give_back` is supplied entirely by
        the caller —the three demos in `frameworks/` file the connection into a queue and do nothing
        else— so nothing else performs it. Task A does `await session.insert(...)`, blows up before
        the commit, its `finally: await session.close()` files the connection away WITH the
        transaction open and the INSERT inside it. Task B takes that connection, runs its SELECT
        inside a stranger's unit of work, and its own `commit()` confirms the INSERT that A
        abandoned. A savepoint is the sharpest case: the name still resolves, so
        `rollback_to_savepoint` on a stranger's mark raises nothing and quietly undoes work.

        The `finally` is the other half: the RETURN is not optional, the CLEAN-UP is what may fail.
        A rollback that raises on a dead socket must not cost the pool a connection for ever.

        Idempotency is kept: a repeated `close()` —the session's plus one from an outer `finally`—
        would return the SAME connection twice, and from then on two tasks would each believe they
        had their own.
        """
        if self._returned:
            return
        self._returned = True
        try:
            await self._inner.rollback()
        finally:
            await self._give_back(self._inner)


class AsyncSnakePool:
    """Hands out async connections and takes them back. Engine-agnostic, like its sibling."""

    def __init__(
        self,
        borrow: AsyncBorrow,
        give_back: AsyncGiveBack,
        close_all: AsyncCloseAll,
        *,
        discard: AsyncDiscard | None = None,
        pre_ping: bool = False,
        recycle_seconds: float | None = None,
        timeout_seconds: float | None = None,
        retry_interval: float = 0.05,
        clock: Clock = monotonic,
    ) -> None:
        self._borrow = borrow
        self._give_back = give_back
        self._close_all = close_all
        self._discard = discard
        self._pre_ping = pre_ping
        self._recycle = recycle_seconds
        self._timeout = timeout_seconds
        self._retry_interval = retry_interval
        self._clock = clock
        # Per object and not per reused `id()`: `id()`s get recycled once the object dies, and the
        # pool would end up measuring the neighbour's age.
        self._born: dict[int, float] = {}

    async def acquire(self) -> AsyncDriver:
        """Lends a HEALTHY connection, wrapped: closing it sends it back to the pool.

        While it waits for one to be freed, it hands control of the loop back (`asyncio.sleep`)
        instead of blocking the thread. That is the only real difference from the synchronous
        sibling, and it is what keeps one task waiting for a connection from stopping the other
        ninety-nine.
        """
        deadline = None if self._timeout is None else self._clock() + self._timeout
        discarded = 0
        while True:
            try:
                inner = await self._borrow()
            except Exception:
                if deadline is None or self._clock() >= deadline:
                    if deadline is None:
                        raise
                    raise SnakePoolTimeout(
                        f"No connection came free in {self._timeout} s. The pool is "
                        f"exhausted for longer than you are willing to wait: either there is too "
                        f"much load or too little pool (or somebody is not giving their "
                        f"connections back)."
                    ) from None
                await asyncio.sleep(self._retry_interval)
                continue
            if await self._usable(inner):
                self._born.setdefault(id(inner), self._clock())
                return _AsyncPooledDriver(inner, self._give_back)
            await self._throw_away(inner)
            discarded += 1
            if discarded >= _MAX_DISCARDS:
                raise SnakePoolTimeout(
                    f"The last {discarded} connections in the pool were dead. This is not one "
                    f"connection being unlucky: the database is not answering (restart, failover, "
                    f"network?). The pool has already thrown them away; retry when it comes back."
                )
            if deadline is not None and self._clock() >= deadline:
                raise SnakePoolTimeout(
                    f"No connection in the pool answered in {self._timeout} s."
                )

    async def _usable(self, inner: AsyncDriver) -> bool:
        """Any good? It looks at the AGE first (free) and then the pulse (costs a trip to the database)."""
        if self._recycle is not None:
            born_at = self._born.get(id(inner))
            if born_at is not None and self._clock() - born_at >= self._recycle:
                return False
        if not self._pre_ping:
            return True
        try:
            await inner.execute("SELECT 1", ())
        except Exception:
            # Any exception: the connection is broken and it does not matter why. Telling the
            # reasons apart here would be putting one engine's jargon into the very piece that
            # exists so as not to have it.
            return False
        return True

    async def _throw_away(self, inner: AsyncDriver) -> None:
        """Takes the connection out of the pool for good. Without `discard`, it at least closes it."""
        self._born.pop(id(inner), None)
        if self._discard is not None:
            await self._discard(inner)
        else:
            await inner.close()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncDriver]:
        """Lends a connection and ALWAYS returns it, even if the block blows up."""
        driver = await self.acquire()
        try:
            yield driver
        finally:
            await driver.close()

    async def close(self) -> None:
        """Closes every connection in the pool."""
        await self._close_all()
