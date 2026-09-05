"""A SYNCHRONOUS driver served as an `AsyncDriver`, on a thread of its own.

All three engines are first class, but only one has a native asyncio library among the project's
deps (psycopg 3). For the other two, the synchronous driver is served from a thread instead of
adding a dependency per engine.

**It is not faking async.** It is exactly what `aiosqlite` does on the inside, and for MySQL it
gives REAL concurrency: Python releases the GIL while the socket waits, so two queries from two
different tasks really do overlap. What it does NOT give is the performance of a native protocol
under heavy concurrency, because every connection takes up a thread.

**One thread per connection, and not a shared pool.** A DBAPI connection is not thread-safe:
`sqlite3` checks and refuses, and PyMySQL simply corrupts itself if two threads use it at once.
With a single thread per driver, the calls serialise by construction and the connection always
sees the same thread. Serialising costs nothing here: a session already waits for each query
before firing the next one, and whoever wants parallelism opens more connections.

Once a native driver exists for an engine, it comes in as its own implementation of the Protocol
and this adapter stops being used for that one. The seam does not change: both are `AsyncDriver`.
"""

from __future__ import annotations

import asyncio
from itertools import islice
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Self, TypeVar

from snakeorm.drivers.base import SnakeDriver

T = TypeVar("T")

_END = object()
"""End-of-iteration sentinel. A `StopIteration` cannot cross a `Future`: asyncio turns it into a
`RuntimeError` and the message says nothing about what actually happened."""


class ThreadedAsyncDriver:
    """Wraps a `SnakeDriver` and exposes it as an `AsyncDriver`, on a dedicated thread."""

    def __init__(self, inner: SnakeDriver, *, executor: ThreadPoolExecutor) -> None:
        self._inner = inner
        self._executor = executor

    @classmethod
    async def open(cls, factory: Callable[[], SnakeDriver]) -> Self:
        """Opens the connection INSIDE the adapter's thread and wraps it.

        Having the thread that will use it open it is not a precaution: `sqlite3` TIES the
        connection to its creating thread and raises `ProgrammingError` if another one touches it,
        so building it outside and using it inside blew up on the first `close()`. With this, the
        connection is born and dies on the same thread.

        `max_workers=1` is what makes the wrapper correct, not a performance knob: a DBAPI
        connection is not thread-safe, and a single thread serialises the calls by construction.
        """
        executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="snakeorm-driver"
        )
        try:
            inner = await asyncio.get_running_loop().run_in_executor(executor, factory)
        except BaseException:
            # If the connection never gets opened, the thread stays alive and the process never ends.
            executor.shutdown(wait=False)
            raise
        return cls(inner, executor=executor)

    async def _run(self, work: Callable[[], T]) -> T:
        """Runs `work` on the driver's thread and waits without blocking the loop."""
        return await asyncio.get_running_loop().run_in_executor(self._executor, work)

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        """Runs the query and returns every row as tuples."""
        return await self._run(lambda: self._inner.fetch_all(sql, params))

    async def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        """Yields the rows WITHOUT materialising them all, crossing the thread once per CHUNK.

        It stays LAZY, at the granularity of `chunk` — which is what `chunk` means everywhere else
        in this ORM, the inner driver included (`sqlite.py` uses `fetchmany(chunk)`). That `chunk`
        governs the round trip to the SERVER; this one governs the crossing of the thread.

        Crossing per ROW instead —a Future, a callback on the loop and waking a thread, for every
        row— measured 103 trips to the executor for 100 rows, where the chunked read costs a
        handful. `islice` is what keeps the laziness and the chunking at the same time, and this is
        the only async path two of the three first-class engines have.

        What a `break` costs goes from one row to one chunk. It never costs the whole result: the
        synchronous iterator is still only advanced as far as it is read.
        """
        iterator: Iterator[tuple[object, ...]] = await self._run(
            lambda: iter(self._inner.fetch_iter(sql, params, chunk=chunk))
        )
        size = max(1, chunk)
        try:
            while True:
                batch = await self._run(lambda: list(islice(iterator, size)))
                if not batch:
                    return
                for row in batch:
                    yield row
        finally:
            # The cursor lives as long as the iteration does; closing it here covers the `break` too.
            await self._run(lambda: iterator.close())  # type: ignore[attr-defined]

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        """Runs a statement fetching no rows; returns how many it affected."""
        return await self._run(lambda: self._inner.execute(sql, params))

    @property
    def last_insert_id(self) -> int:
        """The autoincrement id of the last INSERT. It does not travel to the database: no thread needed."""
        return self._inner.last_insert_id

    async def commit(self) -> None:
        """Commits the transaction in progress."""
        await self._run(self._inner.commit)

    async def rollback(self) -> None:
        """Rolls back the transaction in progress."""
        await self._run(self._inner.rollback)

    async def savepoint(self, name: str) -> None:
        """Opens a named savepoint."""
        await self._run(lambda: self._inner.savepoint(name))

    async def release_savepoint(self, name: str) -> None:
        """Commits the savepoint."""
        await self._run(lambda: self._inner.release_savepoint(name))

    async def rollback_to_savepoint(self, name: str) -> None:
        """Goes back to the savepoint, undoing what was done since it was opened."""
        await self._run(lambda: self._inner.rollback_to_savepoint(name))

    async def close(self) -> None:
        """Closes the connection AND shuts the thread down. Without the second, the process never ends."""
        await self._run(self._inner.close)
        self._executor.shutdown(wait=True)
