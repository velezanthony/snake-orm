"""Tests of `session.iterate()`: walking a big result set WITHOUT materialising all of it.

The gap they close: the `SnakeDriver` Protocol only knew about `fetch_all`. A query of ten million
rows built a Python list with ten million tuples before the user got to see the first one. It was
not a missing method: it was that **the seam did not exist**, and that is why this touched the
Protocol, all four drivers and both sessions at once.

Django has `.iterator()` and SQLAlchemy has `yield_per`; both leaning on a server-side cursor.

The important restriction goes here too: `iterate()` can NOT live together with a to-many
`include()` nor with a `prefetch`. The select-in needs ALL the roots to fire its second query, and
in streaming there are none. It RAISES, it does not silently degrade to N+1 — degrading would be
exactly what the debug panel of this project exists to catch.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.dialects import SQLiteDialect
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.deep_domain import Maker, Nation, Truck


class _ChunkedDriver:
    """Fake driver that serves the rows in chunks and NOTES DOWN how they were asked for.

    It is the only thing that can prove there is streaming: if `iterate()` called `fetch_all` on the
    inside, the test would pass all the same looking only at the results. What is verified is the
    PATH.
    """

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows
        self.fetch_all_calls = 0
        self.iter_calls = 0
        self.chunks_asked: list[int] = []

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.fetch_all_calls += 1
        return list(self._rows)

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        self.iter_calls += 1
        self.chunks_asked.append(chunk)
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


def _session(rows: list[tuple[object, ...]]) -> tuple[SnakeSession, _ChunkedDriver]:
    """A session over the call-counting driver, and the driver itself so it can be interrogated."""
    driver = _ChunkedDriver(rows)
    return SnakeSession(driver, SQLiteDialect()), driver


_NATIONS: list[tuple[object, ...]] = [(1, "España"), (2, "Suecia"), (3, "Alemania")]


def test_iterate_yields_hydrated_models() -> None:
    """Verifies that it returns model instances, not raw tuples."""
    session, _ = _session(_NATIONS)
    names = [nation.name for nation in session.iterate(SnakeQuery(Nation))]
    assert names == ["España", "Suecia", "Alemania"]


def test_iterate_uses_the_streaming_path_not_fetch_all() -> None:
    """Verifies that it goes through `fetch_iter` and NEVER through `fetch_all`.

    This is THE test of this feature: without it, an implementation doing `iter(fetch_all(...))`
    would return exactly the same, would pass every other test, and would not save a single byte.
    """
    session, driver = _session(_NATIONS)
    list(session.iterate(SnakeQuery(Nation)))
    assert (driver.iter_calls, driver.fetch_all_calls) == (1, 0)


def test_iterate_is_lazy_until_consumed() -> None:
    """Verifies that NOTHING runs until the first row is asked for.

    If it ran on construction, an `iterate()` nobody walks would pay for the whole query — and the
    `break` at the tenth row would still drag all ten million along.
    """
    session, driver = _session(_NATIONS)
    stream = session.iterate(SnakeQuery(Nation))
    assert driver.iter_calls == 0
    next(iter(stream))
    assert driver.iter_calls == 1


def test_the_chunk_size_reaches_the_driver() -> None:
    """Verifies that `chunk` is propagated: it is the knob that decides how much memory is used."""
    session, driver = _session(_NATIONS)
    list(session.iterate(SnakeQuery(Nation), chunk=250))
    assert driver.chunks_asked == [250]


def test_iterate_with_a_to_many_include_raises() -> None:
    """Verifies that a to-many `include()` RAISES instead of degrading.

    The select-in needs all the roots to fire the second query, and in streaming they do not exist.
    The ways out would be: materialise (which cancels the streaming) or fall back to one query per
    row (N+1). Both betray what the user asked for, so it is said out loud.
    """
    session, _ = _session(_NATIONS)
    query = SnakeQuery(Nation).include(Nation.makers)
    with pytest.raises(SnakeUnsupportedFeature, match="iterate"):
        next(iter(session.iterate(query)))


def test_iterate_with_a_prefetch_raises() -> None:
    """Verifies that a chained prefetch raises too: it is select-in, level by level."""
    from snakeorm.fields import SnakePrefetch

    session, _ = _session(_NATIONS)
    query = SnakeQuery(Nation).include(SnakePrefetch(Nation.makers))
    with pytest.raises(SnakeUnsupportedFeature, match="iterate"):
        next(iter(session.iterate(query)))


def test_iterate_with_a_to_one_include_is_allowed() -> None:
    """Verifies that a to-ONE `include()` is fine: it travels in the same JOIN, row by row.

    The restriction belongs to the select-in, not to `include` in general. Forbidding both would be
    closing too much, and closing too much is as bad as not closing at all.
    """
    rows: list[tuple[object, ...]] = [(1, "Actros", 10, 10, "Mercedes", 1)]
    driver = _ChunkedDriver(rows)
    session = SnakeSession(driver, SQLiteDialect())
    trucks = list(session.iterate(SnakeQuery(Truck).include(Truck.maker)))
    assert trucks[0].maker.name == "Mercedes"
    assert driver.fetch_all_calls == 0


def test_iterate_over_an_empty_result_yields_nothing() -> None:
    """Verifies that an empty result neither blows up nor returns a phantom row."""
    session, _ = _session([])
    assert list(session.iterate(SnakeQuery(Maker))) == []
