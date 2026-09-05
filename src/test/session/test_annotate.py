"""Tests of session.annotate(): it validates the names, groups by the PK and hydrates the result.

It is tested with a FAKE driver (no Postgres): what is checked is the validation of names, the shape
of the emitted SQL (projection + GROUP BY over the PK), the rejection of an explicit group_by, and
the hydration of the base row and the scalars.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.decorators import SnakeResult, snake_model, snake_result
from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions.functions import count
from snakeorm.fields import SnakeColumn, snake_int, snake_str

from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession


@snake_model(table="annotate_unit_realms")
class _AnnRealm(SnakeModel):
    """Base model for the unit tests of annotate()."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_result
class _AnnRealmStats(SnakeResult[_AnnRealm]):
    """Container: the base row plus one scalar aggregate."""

    realm: _AnnRealm
    forge_count: int


class _FakeDriver:
    """Fake driver: it returns canned rows and records the SQL it ran (no database)."""

    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.calls: list[tuple[str, Sequence[object]]] = []

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.calls.append((sql, params))
        return self.rows

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields what `fetch_all`
        returns. The degradation is written HERE, in plain sight, not done by the framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:  # pragma: no cover
        self.calls.append((sql, params))
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


def test_missing_aggregate_name_raises_before_sql() -> None:
    """An aggregate name is missing: SnakeEmitError before the driver is even touched."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    with pytest.raises(SnakeEmitError, match="do not match the scalar fields.*missing"):
        session.annotate(SnakeQuery(_AnnRealm), _AnnRealmStats)
    assert driver.calls == []


def test_extra_aggregate_name_raises_and_names_it() -> None:
    """There is one aggregate name too many: SnakeEmitError, and the message says which one."""
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    with pytest.raises(
        SnakeEmitError, match=r"do not match the scalar fields.*extra \['extra'\]"
    ):
        session.annotate(
            SnakeQuery(_AnnRealm), _AnnRealmStats, forge_count=count(), extra=count()
        )


def test_projects_base_columns_then_aggregate() -> None:
    """The SQL projects ALL the columns of the base model and then the aggregate, in that order."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.annotate(SnakeQuery(_AnnRealm), _AnnRealmStats, forge_count=count())
    sql, _ = driver.calls[0]
    assert sql.startswith('SELECT "id", "name", COUNT(*)')


def test_groups_by_the_primary_key() -> None:
    """The SQL groups by the PK of the base model (here, the id column)."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.annotate(SnakeQuery(_AnnRealm), _AnnRealmStats, forge_count=count())
    sql, _ = driver.calls[0]
    assert 'GROUP BY "id"' in sql


def test_explicit_group_by_is_rejected() -> None:
    """annotate() over a query with an explicit group_by fails loudly (it groups by the PK)."""
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    with pytest.raises(SnakeEmitError, match="group_by"):
        session.annotate(
            SnakeQuery(_AnnRealm).group_by(_AnnRealm.name),
            _AnnRealmStats,
            forge_count=count(),
        )


def test_hydrates_base_instance_and_scalars() -> None:
    """It hydrates the base row with its columns and builds the result with the scalars."""
    driver = _FakeDriver(rows=[(1, "Nornia", 3)])
    session = SnakeSession(driver, PostgresDialect())
    [stats] = session.annotate(
        SnakeQuery(_AnnRealm), _AnnRealmStats, forge_count=count()
    )
    assert isinstance(stats.realm, _AnnRealm)
    assert (stats.realm.id, stats.realm.name) == (1, "Nornia")
    assert stats.forge_count == 3


def test_query_over_a_different_model_is_rejected() -> None:
    """The query has to query the SAME model that the @snake_result declares."""

    @snake_model(table="annotate_unit_others")
    class _Other(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)

    session = SnakeSession(_FakeDriver(), PostgresDialect())
    with pytest.raises(
        SnakeEmitError, match="the query is over _Other: they do not match"
    ):
        session.annotate(SnakeQuery(_Other), _AnnRealmStats, forge_count=count())
