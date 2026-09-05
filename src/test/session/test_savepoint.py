"""Tests of `session.savepoint()`: the SAVEPOINT context manager (happy, error and nested).

Happy path: it emits `SAVEPOINT` on entry and `RELEASE` on exit. Exception path: it emits
`ROLLBACK TO SAVEPOINT` and RE-RAISES (it does not swallow the exception). Nesting: every level
uses a name unique per depth (`sp1`, `sp2`, ...) and on exit the depth is reset. A FAKE driver is
used that records (op, name) for every savepoint call, without touching the database.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.session import SnakeSession


class _RecordingDriver:
    """Fake driver: it records (operation, name) for every savepoint call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:  # pragma: no cover
        return []

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields what `fetch_all`
        returns. The degradation is written HERE, in plain sight, not done by the framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:  # pragma: no cover
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:  # pragma: no cover
        ...

    def rollback(self) -> None:  # pragma: no cover
        ...

    def savepoint(self, name: str) -> None:
        self.calls.append(("SAVEPOINT", name))

    def release_savepoint(self, name: str) -> None:
        self.calls.append(("RELEASE", name))

    def rollback_to_savepoint(self, name: str) -> None:
        self.calls.append(("ROLLBACK TO", name))

    def close(self) -> None:  # pragma: no cover
        ...


def test_savepoint_happy_path_emits_savepoint_then_release() -> None:
    """Happy path: on entry it emits SAVEPOINT and on a clean exit, RELEASE (it consolidates)."""
    driver = _RecordingDriver()
    session = SnakeSession(driver, PostgresDialect())
    with session.savepoint():
        pass
    assert driver.calls == [("SAVEPOINT", "sp1"), ("RELEASE", "sp1")]


def test_savepoint_rolls_back_and_reraises_on_exception() -> None:
    """Exception path: it emits ROLLBACK TO SAVEPOINT, does NOT RELEASE, and RE-RAISES the error."""
    driver = _RecordingDriver()
    session = SnakeSession(driver, PostgresDialect())
    with pytest.raises(ValueError, match="boom"), session.savepoint():
        raise ValueError("boom")
    assert driver.calls == [("SAVEPOINT", "sp1"), ("ROLLBACK TO", "sp1")]


def test_savepoint_nesting_uses_distinct_names() -> None:
    """Nested: each level uses a different name (sp1, sp2) and they release inside-out."""
    driver = _RecordingDriver()
    session = SnakeSession(driver, PostgresDialect())
    with session.savepoint(), session.savepoint():
        pass
    assert driver.calls == [
        ("SAVEPOINT", "sp1"),
        ("SAVEPOINT", "sp2"),
        ("RELEASE", "sp2"),
        ("RELEASE", "sp1"),
    ]


def test_savepoint_depth_resets_after_block() -> None:
    """After leaving the block the depth is reset: the next savepoint is `sp1` again."""
    driver = _RecordingDriver()
    session = SnakeSession(driver, PostgresDialect())
    with session.savepoint():
        pass
    with session.savepoint():
        pass
    assert driver.calls == [
        ("SAVEPOINT", "sp1"),
        ("RELEASE", "sp1"),
        ("SAVEPOINT", "sp1"),
        ("RELEASE", "sp1"),
    ]


def test_savepoint_depth_resets_even_after_exception() -> None:
    """Even after an exception the depth is decremented (the `finally`): the next one is `sp1`."""
    driver = _RecordingDriver()
    session = SnakeSession(driver, PostgresDialect())
    with pytest.raises(ValueError):  # noqa: PT012 - the block is needed for the second savepoint
        with session.savepoint():
            raise ValueError("boom")
    with session.savepoint():
        pass
    assert driver.calls == [
        ("SAVEPOINT", "sp1"),
        ("ROLLBACK TO", "sp1"),
        ("SAVEPOINT", "sp1"),
        ("RELEASE", "sp1"),
    ]
