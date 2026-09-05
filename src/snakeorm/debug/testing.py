"""`assert_queries`: a test assertion on how many statements a block runs (like Django's `assertNumQueries`).

When it fails it shows the queries that ran, not just that the number does not add up.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from snakeorm.debug.collector import DebugCollector, capture_queries


@contextmanager
def assert_queries(expected: int) -> Iterator[DebugCollector]:
    """Assert the block runs EXACTLY `expected` statements, or raise `AssertionError`."""
    with capture_queries() as collector:
        yield collector
    report = collector.report()
    if report.count != expected:
        raise AssertionError(
            f"Expected {expected} queries, {report.count} ran:\n{report.to_text()}"
        )
