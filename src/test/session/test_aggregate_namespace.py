"""Tests of the `obj.aggregate.<name>` escape hatch: it returns the annotated value or fails loudly.

The escape hatch is the EMERGENCY EXIT (it returns object, it demands a cast). What is checked here
is that after annotate() it returns the value, that a non-annotated instance raises
SnakeAggregateNotLoaded, and that asking for a name that does not exist names the annotations that
are available.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.decorators import SnakeResult, snake_model, snake_result
from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeAggregateNotLoaded
from snakeorm.expressions.functions import count
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession


@snake_model(table="namespace_realms")
class _NsRealm(SnakeModel):
    """Base model for exercising the aggregate escape hatch."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_result
class _NsRealmStats(SnakeResult[_NsRealm]):
    """Container carrying a single scalar aggregate."""

    realm: _NsRealm
    forge_count: int


class _FakeDriver:
    """Fake driver: it returns canned rows (no database)."""

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return self.rows

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

    def savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def release_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def rollback_to_savepoint(self, name: str) -> None:  # pragma: no cover
        ...

    def close(self) -> None:  # pragma: no cover
        ...


def test_escape_hatch_returns_the_annotated_value() -> None:
    """After annotate(), obj.aggregate.<name> returns the value of the aggregate."""
    session = SnakeSession(_FakeDriver(rows=[(1, "Nornia", 3)]), PostgresDialect())
    [stats] = session.annotate(SnakeQuery(_NsRealm), _NsRealmStats, forge_count=count())
    assert stats.realm.aggregate.forge_count == 3


def test_unannotated_instance_raises() -> None:
    """An instance that was never annotated raises SnakeAggregateNotLoaded when asked for one."""
    realm = _NsRealm(id=1, name="Nornia")
    with pytest.raises(
        SnakeAggregateNotLoaded, match="This instance was not annotated"
    ):
        _ = realm.aggregate.forge_count


def test_unknown_aggregate_lists_available_annotations() -> None:
    """Asking for a nonexistent aggregate names the available annotations in the message."""
    session = SnakeSession(_FakeDriver(rows=[(1, "Nornia", 3)]), PostgresDialect())
    [stats] = session.annotate(SnakeQuery(_NsRealm), _NsRealmStats, forge_count=count())
    with pytest.raises(SnakeAggregateNotLoaded, match="forge_count"):
        _ = stats.realm.aggregate.missing
