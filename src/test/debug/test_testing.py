"""`assert_queries`: the equivalent of Django's `assertNumQueries`, built on top of the capture.

Pure gold for a type-first ORM: it turns "my include is not N+1" into a test ASSERTION. If the block
runs a number of queries other than the expected one, it fails showing which ones ran —so that the
message says WHAT happened, not just that the number does not add up—.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.debug import CaptureDriver, assert_queries


class _Inner:
    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return [(1,)]

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields whatever
        `fetch_all` returns. The degradation is written HERE, in plain sight, not done by the framework."""
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


def test_passes_when_count_matches() -> None:
    """If the number of queries matches, the block passes without noise."""
    driver = CaptureDriver(_Inner())
    with assert_queries(2):
        driver.fetch_all("SELECT 1", ())
        driver.fetch_all("SELECT 2", ())


def test_fails_when_count_differs() -> None:
    """If more (or fewer) queries run than expected, AssertionError fires."""
    driver = CaptureDriver(_Inner())
    with pytest.raises(AssertionError, match="Expected 1 queries"):
        with assert_queries(1):
            driver.fetch_all("SELECT 1", ())
            driver.fetch_all("SELECT 2", ())  # one too many
