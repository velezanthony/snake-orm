"""The instant a query STARTED, and the engine that ran it, on every `QueryRecord`.

`duration_ms` alone cannot place a query on a timeline: a span needs an absolute start and an
absolute end. The start is not computed, it is KEPT — `CaptureDriver` already reads `perf_counter()`
to measure the duration, so the first half of that subtraction is what gets stored.

The cost with the debug OFF is the point of the last two tests: the passthrough must stay one
`ContextVar` read, so `perf_counter` is never even called when there is no scope.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Sequence
from time import perf_counter

import pytest

from snakeorm.debug import (
    AsyncCaptureDriver,
    CaptureDriver,
    capture_queries,
)


class _Inner:
    """Fake synchronous driver: it answers fixed rows and records nothing else."""

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return [(1,)]

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: no engine to stream from, so it yields what `fetch_all` returns."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        return 1

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

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        return [(1,)]

    async def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        """Test double: no engine to stream from, so it yields what `fetch_all` returns."""
        for row in await self.fetch_all(sql, params):
            yield row

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        return 1

    @property
    def last_insert_id(self) -> int:
        return 0

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def savepoint(self, name: str) -> None: ...
    async def release_savepoint(self, name: str) -> None: ...
    async def rollback_to_savepoint(self, name: str) -> None: ...
    async def close(self) -> None: ...


def test_record_carries_the_monotonic_start() -> None:
    """A captured record keeps the `perf_counter()` reading taken before the statement ran."""
    driver = CaptureDriver(_Inner())
    before = perf_counter()
    with capture_queries() as collector:
        driver.fetch_all("SELECT 1", ())
    after = perf_counter()

    record = collector.report().records[0]
    assert before <= record.started_at <= after


def test_the_start_precedes_the_end() -> None:
    """`started_at + duration` never lands after the moment the scope closed: the span fits."""
    driver = CaptureDriver(_Inner())
    with capture_queries() as collector:
        driver.fetch_all("SELECT 1", ())
    after = perf_counter()

    record = collector.report().records[0]
    assert record.started_at + record.duration_ms / 1000 <= after


def test_starts_are_ordered_like_the_queries() -> None:
    """Consecutive statements get non-decreasing starts, so the timeline reads in the order they ran."""
    driver = CaptureDriver(_Inner())
    with capture_queries() as collector:
        driver.fetch_all("SELECT 1", ())
        driver.execute("UPDATE t SET a = 1", ())
        list(driver.fetch_iter("SELECT 2", ()))

    starts = [record.started_at for record in collector.report().records]
    assert starts == sorted(starts)


def test_async_record_carries_the_monotonic_start() -> None:
    """The asynchronous mirror keeps the same start: one seam, the same measurement."""
    driver = AsyncCaptureDriver(_AsyncInner())

    async def run() -> float:
        with capture_queries() as collector:
            await driver.fetch_all("SELECT 1", ())
        return collector.report().records[0].started_at

    before = perf_counter()
    started_at = asyncio.run(run())
    assert before <= started_at <= perf_counter()


def test_record_carries_the_engine_that_ran_it() -> None:
    """The driver DECLARES its engine and every record it captures carries it, for `db.system.name`."""
    driver = CaptureDriver(_Inner(), system="postgresql")
    with capture_queries() as collector:
        driver.fetch_all("SELECT 1", ())

    assert collector.report().records[0].system == "postgresql"


def test_an_undeclared_engine_is_empty_not_guessed() -> None:
    """Without a declared engine the field is empty: the exporter omits the attribute rather than lie."""
    driver = CaptureDriver(_Inner())
    with capture_queries() as collector:
        driver.fetch_all("SELECT 1", ())

    assert collector.report().records[0].system == ""


def test_async_driver_declares_its_engine_too() -> None:
    """`AsyncCaptureDriver` takes the same declaration: the two colours say the same thing."""
    driver = AsyncCaptureDriver(_AsyncInner(), system="sqlite")

    async def run() -> str:
        with capture_queries() as collector:
            await driver.fetch_all("SELECT 1", ())
        return collector.report().records[0].system

    assert asyncio.run(run()) == "sqlite"


def test_passthrough_never_reads_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """With NO scope the driver does not even call `perf_counter`: the debug-off cost does not grow.

    The passthrough is one `ContextVar` read and nothing else. A clock reading added on that path
    would be paid by every query of every application that never turns the debug on.
    """
    calls = 0

    def counting() -> float:
        nonlocal calls
        calls += 1
        return 0.0

    monkeypatch.setattr("snakeorm.debug.capture.perf_counter", counting)
    driver = CaptureDriver(_Inner())
    driver.fetch_all("SELECT 1", ())
    driver.execute("UPDATE t SET a = 1", ())
    list(driver.fetch_iter("SELECT 2", ()))

    assert calls == 0


def test_async_passthrough_never_reads_the_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The asynchronous passthrough pays the same nothing: one `ContextVar` read."""
    calls = 0

    def counting() -> float:
        nonlocal calls
        calls += 1
        return 0.0

    monkeypatch.setattr("snakeorm.debug.capture.perf_counter", counting)
    driver = AsyncCaptureDriver(_AsyncInner())

    async def run() -> None:
        await driver.fetch_all("SELECT 1", ())
        await driver.execute("UPDATE t SET a = 1", ())
        async for _ in driver.fetch_iter("SELECT 2", ()):
            pass

    asyncio.run(run())
    assert calls == 0
