"""Async streaming must cross the executor once per CHUNK, not once per ROW.

`ThreadedAsyncDriver.fetch_iter` did `await self._run(lambda: next(iterator, _END))` INSIDE the row
loop. `_run` is `run_in_executor`: a Future, a callback on the loop, and waking a thread — per row.

It is the only async path two of the three first-class engines have (SQLite and MySQL); the Postgres
one is native and never had this shape.

The docstring defended it with a dichotomy that is false: "if this did a `fetch_all` and yielded
afterwards, async streaming would be an `all()` under another name". There is a third option.
`islice(iterator, chunk)` is lazy at the granularity of `chunk` — which is what `chunk` already
means everywhere else in this ORM, including in the inner driver, where `sqlite.py` has been doing
`fetchmany(chunk)` all along. That `chunk` governs the round trip to the SERVER; this one governs
the crossing of the thread, and only one of the two was being used.

WHAT THIS ASSERTS: the number of crossings, not microseconds. A timing assertion on a thread pool is
a flake generator, and the count is the actual claim — the wall-clock follows from it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from snakeorm.drivers.threaded import ThreadedAsyncDriver

_ROWS = 100


_T = TypeVar("_T")


class _Countable(ThreadedAsyncDriver):
    """A driver that counts how many times work crossed to its thread.

    The override keeps the generic signature: narrowing it to `object` would make the counter type
    differently from the thing it counts, and mypy is right to refuse that.
    """

    def __init__(self, inner: object, *, executor: ThreadPoolExecutor) -> None:
        super().__init__(inner, executor=executor)  # type: ignore[arg-type]
        self.crossings = 0

    async def _run(self, work: Callable[[], _T]) -> _T:
        self.crossings += 1
        return await super()._run(work)


class _Source:
    """A synchronous driver that streams `_ROWS` rows and nothing else."""

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        for n in range(_ROWS):
            yield (n,)

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return list(self.fetch_iter(sql, params))

    def execute(self, sql: str, params: Sequence[object]) -> int:
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


def _drain(chunk: int) -> tuple[int, list[tuple[object, ...]]]:
    """Streams every row with that chunk size, returning (crossings, rows)."""
    executor = ThreadPoolExecutor(max_workers=1)
    driver = _Countable(_Source(), executor=executor)

    async def scenario() -> list[tuple[object, ...]]:
        return [row async for row in driver.fetch_iter("SELECT 1", (), chunk=chunk)]

    try:
        rows = asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)
    return driver.crossings, rows


def test_streaming_crosses_the_thread_once_per_chunk() -> None:
    """100 rows with `chunk=25` cost a handful of crossings, not 100 of them.

    The ceiling is deliberately loose —it is not measuring an exact protocol— but far below one per
    row, which is the only thing that distinguishes the two implementations.
    """
    crossings, rows = _drain(chunk=25)

    assert len(rows) == _ROWS, "the rows themselves have to survive the change"
    assert crossings <= 12, (
        f"{crossings} trips to the executor for {_ROWS} rows: it is still crossing per row"
    )


def test_every_row_still_arrives_and_in_order() -> None:
    """The floor: batching must not drop, duplicate or reorder anything."""
    _, rows = _drain(chunk=7)

    assert rows == [(n,) for n in range(_ROWS)]


def test_a_consumer_that_breaks_early_does_not_pay_for_the_rest() -> None:
    """Laziness is kept, at the granularity of `chunk` — which is what `chunk` means here.

    This is the property the old shape was protecting, and it is worth pinning: the point of the
    change is that the price of a `break` goes from "one row" to "one chunk", not to "all of them".
    """
    executor = ThreadPoolExecutor(max_workers=1)
    driver = _Countable(_Source(), executor=executor)

    async def scenario() -> int:
        seen = 0
        async for _row in driver.fetch_iter("SELECT 1", (), chunk=10):
            seen += 1
            if seen == 3:
                break
        return seen

    try:
        assert asyncio.run(scenario()) == 3
    finally:
        executor.shutdown(wait=True)

    assert driver.crossings <= 4, (
        f"{driver.crossings} crossings to read 3 rows: the break paid for the whole result"
    )
