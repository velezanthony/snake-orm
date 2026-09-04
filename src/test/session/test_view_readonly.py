"""A VIEW is queried as usual, but it is NOT written to (the read-only lock).

Reading (`all`/`first`) over a view works: that is what makes it useful. Writing
(`add`/`update`/`delete`/`upsert`/`update_where`/`delete_where`) is forbidden. The main lock is one
of TYPES (the write methods ask for a `SnakeModel`, which a `SnakeView` is not); what is tested here
is the runtime BACKSTOP, which raises `SnakeUnsupportedFeature` with a clear message.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, cast

import pytest

from snakeorm.decorators import snake_view
from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.model import SnakeView
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession


@snake_view(sql="SELECT user_id, class_name FROM ro_enrollments")
class RoUserClasses(SnakeView):
    """Read-only view used to exercise the write lock."""

    user_id: SnakeColumn[int] = snake_int()
    class_name: SnakeColumn[str] = snake_str()


class _FakeDriver:
    """Fake driver: it returns fixed rows from fetch_all and records the executes (no database)."""

    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []
        self.executed: list[str] = []

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return self.rows

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields what `fetch_all`
        returns. The degradation is written HERE, in plain sight, not done by the framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.executed.append(sql)
        return 0

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:  # pragma: no cover
        ...

    def rollback(self) -> None:  # pragma: no cover
        ...

    def savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def release_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def rollback_to_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def close(self) -> None:  # pragma: no cover
        ...


def _session(rows: list[tuple[object, ...]] | None = None) -> SnakeSession:
    """Session wired to a fake driver (no database)."""
    return SnakeSession(_FakeDriver(rows), PostgresDialect())


def test_query_over_a_view_works() -> None:
    """Querying a view with `all()` works: it hydrates typed rows like any other model."""
    session = _session([(1, "Álgebra"), (2, "Física")])
    rows = session.all(SnakeQuery(RoUserClasses))
    assert [(r.user_id, r.class_name) for r in rows] == [(1, "Álgebra"), (2, "Física")]


def test_add_of_a_view_is_rejected_at_runtime() -> None:
    """`session.add(view)` raises SnakeUnsupportedFeature (the runtime backstop of the lock)."""
    session = _session()
    instance = cast("Any", RoUserClasses(user_id=1, class_name="Álgebra"))
    with pytest.raises(SnakeUnsupportedFeature, match="is a READ-ONLY view"):
        session.add(instance)


def test_update_of_a_view_is_rejected_at_runtime() -> None:
    """`session.update(view)` raises SnakeUnsupportedFeature: a view is not written to."""
    session = _session()
    instance = cast("Any", RoUserClasses(user_id=1, class_name="Álgebra"))
    with pytest.raises(SnakeUnsupportedFeature, match="is a READ-ONLY view"):
        session.update(instance)


def test_delete_of_a_view_is_rejected_at_runtime() -> None:
    """`session.delete(view)` raises SnakeUnsupportedFeature: a view is not deleted from."""
    session = _session()
    instance = cast("Any", RoUserClasses(user_id=1, class_name="Álgebra"))
    with pytest.raises(SnakeUnsupportedFeature, match="is a READ-ONLY view"):
        session.delete(instance)


def test_bulk_delete_where_over_a_view_is_rejected() -> None:
    """`delete_where` over a view query raises (the read-only lock on the bulk write path too)."""
    session = _session()
    query = cast("Any", SnakeQuery(RoUserClasses).filter(RoUserClasses.user_id == 1))
    with pytest.raises(
        SnakeUnsupportedFeature,
        match="READ-ONLY view: it does not accept a bulk DELETE",
    ):
        session.delete_where(query)
