"""Runtime capture: the per-scope collector and the driver decorators.

`capture_queries()` opens a scope based on `contextvars` —it works the same in sync and in async, and
it does not get contaminated between concurrent requests—. `CaptureDriver`/`AsyncCaptureDriver` record
every statement ONLY if there is an active scope: outside of it they are pure passthrough, almost zero
cost. That is the reason this beats Django's global `DEBUG`: it is per-scope, not global state.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Sequence

from snakeorm.debug import (
    AsyncCaptureDriver,
    CaptureDriver,
    QueryKind,
    capture_queries,
    current_collector,
)


class _Inner:
    """Fake synchronous driver: it records the SQL and returns fixed rows."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.calls.append(sql)
        return [(1,), (2,)]

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields whatever
        `fetch_all` returns. The degradation is written HERE, in plain sight, not done by the framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.calls.append(sql)
        return 3

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


class _AsyncInner:
    """Fake asynchronous driver, a mirror of `_Inner`."""

    async def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields whatever
        `fetch_all` returns. The degradation is written HERE, in plain sight, not done by the framework."""
        for row in await self.fetch_all(sql, params):
            yield row

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        self.calls.append(sql)
        return [(1,), (2,)]

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        self.calls.append(sql)
        return 3

    @property
    def last_insert_id(self) -> int:
        """The id of the last INSERT. Test double: it writes nothing, so 0."""
        return 0

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def savepoint(self, name: str) -> None: ...
    async def release_savepoint(self, name: str) -> None: ...
    async def rollback_to_savepoint(self, name: str) -> None: ...
    async def close(self) -> None: ...


def test_capture_collects_statements() -> None:
    """Inside a scope, every fetch_all/execute gets recorded with its kind and rows."""
    driver = CaptureDriver(_Inner())
    with capture_queries() as collector:
        driver.fetch_all("SELECT 1", ())
        driver.execute("INSERT INTO t VALUES (1)", ())
    report = collector.report()
    assert report.count == 2
    assert report.records[0].kind is QueryKind.SELECT
    assert report.records[0].rows == 2  # the fake's two rows
    assert report.records[1].kind is QueryKind.WRITE
    assert report.records[1].rows == 3  # the execute's rowcount


def test_sequence_numbers_are_assigned_in_order() -> None:
    """The records are numbered 1..N in the order they ran (so an N+1 can be read)."""
    driver = CaptureDriver(_Inner())
    with capture_queries() as collector:
        driver.fetch_all("SELECT 1", ())
        driver.fetch_all("SELECT 2", ())
    assert [record.n for record in collector.report().records] == [1, 2]


def test_passthrough_when_no_scope() -> None:
    """With no active scope the decorator records nothing and delegates as is: almost zero cost."""
    inner = _Inner()
    driver = CaptureDriver(inner)
    assert driver.fetch_all("SELECT 1", ()) == [(1,), (2,)]
    assert inner.calls == ["SELECT 1"]  # it did run
    assert current_collector() is None  # but there is nowhere to record it


def test_scope_resets_on_exit() -> None:
    """On leaving the `with`, the active collector goes back to None: there is no leak between scopes."""
    assert current_collector() is None
    with capture_queries():
        assert current_collector() is not None
    assert current_collector() is None


def test_async_capture_collects() -> None:
    """The async decorator records just the same inside the same scope through contextvars."""
    driver = AsyncCaptureDriver(_AsyncInner())

    async def run() -> int:
        with capture_queries() as collector:
            await driver.fetch_all("SELECT 1", ())
            await driver.execute("UPDATE t SET x=1", ())
        return collector.report().count

    assert asyncio.run(run()) == 2
