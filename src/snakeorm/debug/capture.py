"""`CaptureDriver` / `AsyncCaptureDriver`: driver decorators that record each statement into the scope's collector.

With no active scope they delegate without timing or recording: with the debug off, the cost is one `ContextVar` read.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from time import perf_counter

from snakeorm.debug.collector import current_collector
from snakeorm.debug.record import QueryKind
from snakeorm.drivers.asyncbase import AsyncDriver
from snakeorm.drivers.base import SnakeDriver


class CaptureDriver:
    """Wrap a `SnakeDriver` and record each statement into the active collector (if there is one)."""

    __slots__ = ("_inner", "_system")

    def __init__(self, inner: SnakeDriver, *, system: str = "") -> None:
        """`system` is the engine's OpenTelemetry name (`db.system.name`), DECLARED by the caller.

        It is read once here and copied onto every record, so the per-query cost is an attribute
        read. It is not derived from the driver's class: a decorator chain (pool, timeout, logging)
        would hide it, and guessing from the SQL cannot tell MySQL from MariaDB.
        """
        self._inner = inner
        self._system = system

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        """Run the read; if there is a scope, record SQL, time and rows returned."""
        collector = current_collector()
        if collector is None:
            return self._inner.fetch_all(sql, params)
        start = perf_counter()
        rows = self._inner.fetch_all(sql, params)
        collector.add(
            sql=sql,
            params=params,
            duration_ms=(perf_counter() - start) * 1000,
            rows=len(rows),
            kind=QueryKind.SELECT,
            started_at=start,
            system=self._system,
        )
        return rows

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Yield the rows in streaming; if there is a scope, record SQL, time and rows CONSUMED.

        It gets noted at the end, not at the start, and for two reasons. The first is that counting
        beforehand would demand materialising the result, which is exactly what this path avoids.
        The second is that in streaming the interesting figure IS what was consumed: a `break` at
        the tenth row out of a million counts ten, and that is what the panel must show.

        The measured time includes whatever the consumer takes between rows. It is unavoidable —the
        cursor stays open that whole time— and it is also honest: that is how long the query lasts
        from the point of view of the connection, which is the one being held.
        """
        collector = current_collector()
        if collector is None:
            yield from self._inner.fetch_iter(sql, params, chunk=chunk)
            return
        start = perf_counter()
        consumed = 0
        try:
            for row in self._inner.fetch_iter(sql, params, chunk=chunk):
                consumed += 1
                yield row
        finally:
            collector.add(
                sql=sql,
                params=params,
                duration_ms=(perf_counter() - start) * 1000,
                rows=consumed,
                kind=QueryKind.SELECT,
                started_at=start,
                system=self._system,
            )

    def execute(self, sql: str, params: Sequence[object]) -> int:
        """Run the write; if there is a scope, record SQL, time and rows affected."""
        collector = current_collector()
        if collector is None:
            return self._inner.execute(sql, params)
        start = perf_counter()
        affected = self._inner.execute(sql, params)
        collector.add(
            sql=sql,
            params=params,
            duration_ms=(perf_counter() - start) * 1000,
            rows=affected,
            kind=QueryKind.WRITE,
            started_at=start,
            system=self._system,
        )
        return affected

    @property
    def last_insert_id(self) -> int:
        """Forward to the wrapped driver (see the `SnakeDriver` Protocol)."""
        return self._inner.last_insert_id

    def commit(self) -> None:
        """Delegate the commit."""
        self._inner.commit()

    def rollback(self) -> None:
        """Delegate the rollback."""
        self._inner.rollback()

    def savepoint(self, name: str) -> None:
        """Delegate the savepoint."""
        self._inner.savepoint(name)

    def release_savepoint(self, name: str) -> None:
        """Delegate the savepoint release."""
        self._inner.release_savepoint(name)

    def rollback_to_savepoint(self, name: str) -> None:
        """Delegate the rollback to the savepoint."""
        self._inner.rollback_to_savepoint(name)

    def close(self) -> None:
        """Close the inner driver."""
        self._inner.close()


class AsyncCaptureDriver:
    """Asynchronous mirror of `CaptureDriver`, over the `AsyncDriver` Protocol."""

    __slots__ = ("_inner", "_system")

    def __init__(self, inner: AsyncDriver, *, system: str = "") -> None:
        """Same declaration as the synchronous one: the engine's `db.system.name`, given not guessed."""
        self._inner = inner
        self._system = system

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        """Run the async read; if there is a scope, record SQL, time and rows returned."""
        collector = current_collector()
        if collector is None:
            return await self._inner.fetch_all(sql, params)
        start = perf_counter()
        rows = await self._inner.fetch_all(sql, params)
        collector.add(
            sql=sql,
            params=params,
            duration_ms=(perf_counter() - start) * 1000,
            rows=len(rows),
            kind=QueryKind.SELECT,
            started_at=start,
            system=self._system,
        )
        return rows

    async def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        """Async mirror of `CaptureDriver.fetch_iter`: it records the rows CONSUMED, at the end."""
        collector = current_collector()
        if collector is None:
            async for row in self._inner.fetch_iter(sql, params, chunk=chunk):
                yield row
            return
        start = perf_counter()
        consumed = 0
        try:
            async for row in self._inner.fetch_iter(sql, params, chunk=chunk):
                consumed += 1
                yield row
        finally:
            collector.add(
                sql=sql,
                params=params,
                duration_ms=(perf_counter() - start) * 1000,
                rows=consumed,
                kind=QueryKind.SELECT,
                started_at=start,
                system=self._system,
            )

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        """Run the async write; if there is a scope, record SQL, time and rows affected."""
        collector = current_collector()
        if collector is None:
            return await self._inner.execute(sql, params)
        start = perf_counter()
        affected = await self._inner.execute(sql, params)
        collector.add(
            sql=sql,
            params=params,
            duration_ms=(perf_counter() - start) * 1000,
            rows=affected,
            kind=QueryKind.WRITE,
            started_at=start,
            system=self._system,
        )
        return affected

    @property
    def last_insert_id(self) -> int:
        """Delegate the id of the last INSERT: capturing the SQL does not change what the engine wrote."""
        return self._inner.last_insert_id

    async def commit(self) -> None:
        """Delegate the commit."""
        await self._inner.commit()

    async def rollback(self) -> None:
        """Delegate the rollback."""
        await self._inner.rollback()

    async def savepoint(self, name: str) -> None:
        """Delegate the savepoint."""
        await self._inner.savepoint(name)

    async def release_savepoint(self, name: str) -> None:
        """Delegate the savepoint release."""
        await self._inner.release_savepoint(name)

    async def rollback_to_savepoint(self, name: str) -> None:
        """Delegate the rollback to the savepoint."""
        await self._inner.rollback_to_savepoint(name)

    async def close(self) -> None:
        """Close the inner driver."""
        await self._inner.close()
