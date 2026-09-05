"""Tests of the MAPPING stopwatch: how long the ORM spends turning rows into objects.

`app_ms` used to be one opaque block (`wall - db`) mixing three things: the ORM's mapping, the
user's Python and the template. With the three fused, the panel cannot answer the one question
where the ORM is the suspect — "is it you or is it me?".

The stopwatch is read ONCE PER RESULT SET and never per row. That is the whole design constraint:
a `ContextVar` read inside the hydration loop measured +52 ns/row (+4.3% on a five-column row) with
the debug OFF, and the hottest path of the ORM does not pay for a number nobody asked for. It is a
DECORATOR on the callables that turn rows into objects, not a `with` block, for the same reason
measured one level down: an equivalent `@contextmanager` costs ~1000 ns per result set against the
decorator's ~130, and a one-row `get()` maps in ~1.5 us.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.debug.collector import capture_queries, timed_mapping
from snakeorm.dialects import SQLiteDialect
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.deep_domain import Nation


class _RowDriver:
    """Fake driver serving fixed rows: the mapping is what is under test, not the SQL."""

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return list(self._rows)

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        yield from self._rows

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


_NATIONS: list[tuple[object, ...]] = [(i, f"n{i}") for i in range(1, 21)]


def _session() -> SnakeSession:
    """A session over the fake driver, with no engine anywhere near it."""
    return SnakeSession(_RowDriver(_NATIONS), SQLiteDialect())


@timed_mapping
def _mapped(rows: list[int]) -> list[int]:
    """A stand-in for a mapping callable: it takes rows and gives objects back."""
    return [row * 2 for row in rows]


def test_the_stopwatch_hands_back_what_the_wrapped_callable_returned() -> None:
    """Outside a capture scope it only delegates: same result, nothing timed and nothing recorded."""
    assert _mapped([1, 2, 3]) == [2, 4, 6]


def test_the_stopwatch_accumulates_into_the_active_collector() -> None:
    """Inside a scope, every timed batch ADDS to the scope's mapping total."""
    with capture_queries() as collector:
        _mapped([1, 2, 3])
        _mapped([4, 5, 6])

    mapping_ms = collector.report().mapping_ms
    assert mapping_ms is not None
    assert mapping_ms >= 0.0


def test_the_stopwatch_records_even_when_the_mapping_raises() -> None:
    """A batch that blows up mid-way still reports the time it burned before failing.

    Otherwise a request that died inside the mapper would show that time inside `app_ms`, blaming
    the user's code for what the ORM was doing.
    """

    @timed_mapping
    def exploding(rows: list[int]) -> list[int]:
        """Fails on purpose, after having spent some time."""
        raise ValueError("boom")

    with capture_queries() as collector:
        with pytest.raises(ValueError):
            exploding([1])

    assert collector.report().mapping_ms is not None


def test_a_scope_that_mapped_nothing_reports_zero_not_unknown() -> None:
    """An open scope always KNOWS its mapping: zero measured is a fact, not an absence."""
    with capture_queries() as collector:
        pass

    assert collector.report().mapping_ms == 0.0


def test_all_feeds_the_mapping_clock() -> None:
    """`session.all()` is timed: the rows it hydrates land in the scope's mapping total."""
    with capture_queries() as collector:
        rows = _session().all(SnakeQuery(Nation))

    mapping_ms = collector.report().mapping_ms
    assert len(rows) == len(_NATIONS)
    assert mapping_ms is not None and mapping_ms > 0.0


def test_the_clock_is_read_once_per_result_set_not_once_per_row() -> None:
    """The scope lookup happens ONCE for the whole batch, never inside the row loop.

    This is the off-switch cost guarantee written as a test. Reading the `ContextVar` per row costs
    +4.3% on the hydration loop with the debug turned off, and no measurement is worth that on the
    path every single read of the ORM goes through. Counting the lookups is the only way to catch a
    future refactor that moves the stopwatch one level down.
    """
    import snakeorm.debug.collector as collector_module

    lookups = 0
    original = collector_module.current_collector

    def counting() -> object | None:
        nonlocal lookups
        lookups += 1
        return original()

    collector_module.current_collector = counting  # type: ignore[assignment]
    try:
        _session().all(SnakeQuery(Nation))
    finally:
        collector_module.current_collector = original  # type: ignore[assignment]

    assert lookups <= 1, (
        f"{lookups} scope lookups for {len(_NATIONS)} rows: the stopwatch moved into the row loop"
    )
