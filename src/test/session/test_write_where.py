"""Tests of BULK writing in the session: `update_where` and `delete_where`.

Per-object writing (`update`/`delete`) filters by PK; the BULK one uses the WHERE of a query and
returns the rowcount. It is tested with a FAKE driver (no database): the SQL, the params, the
rowcount and the safety GUARDS. The arithmetic `{views: views + 1}` emits `SET "views" =
("views" + %s)`. An UPDATE/DELETE with no filter, or with limit/order/include, MUST raise.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.fields import SnakeColumn, snake_int

from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.deep_domain import Truck


@snake_model(table="ww_counters")
class _Counter(SnakeModel):
    """Test model for the bulk write path."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    views: SnakeColumn[int] = snake_int()


class _FakeDriver:
    """Fake driver: it records the SQL it ran and returns a configurable rowcount (no database)."""

    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount
        self.calls: list[tuple[str, Sequence[object]]] = []

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return []

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields what `fetch_all`
        returns. The degradation is written HERE, in plain sight, not done by the framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.calls.append((sql, params))
        return self.rowcount

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


def test_update_where_emits_sql_params_and_returns_rowcount() -> None:
    """Verifies that update_where emits the UPDATE with WHERE, passes the params, returns rowcount."""
    driver = _FakeDriver(rowcount=5)
    session = SnakeSession(driver, PostgresDialect())
    affected = session.update_where(
        SnakeQuery(_Counter).filter(_Counter.id == 1), [(_Counter.views, 0)]
    )
    sql, params = driver.calls[0]
    assert sql == 'UPDATE "public"."ww_counters" SET "views" = %s WHERE "id" = %s'
    assert params == (0, 1)
    assert affected == 5


def test_update_where_arithmetic_emits_column_expression() -> None:
    """Verifies that `{views: views + 1}` emits `SET "views" = ("views" + %s)` (in-place maths)."""
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.update_where(
        SnakeQuery(_Counter).filter(_Counter.id == 1),
        [(_Counter.views, _Counter.views + 1)],
    )
    sql, params = driver.calls[0]
    assert sql == (
        'UPDATE "public"."ww_counters" SET "views" = ("views" + %s) WHERE "id" = %s'
    )
    assert params == (1, 1)


def test_update_where_without_filter_raises() -> None:
    """Verifies the GUARD: a bulk UPDATE with no WHERE would flatten the table → it raises."""
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    with pytest.raises(
        SnakeUnsupportedFeature,
        match="a UPDATE without a WHERE would affect the WHOLE table",
    ):
        session.update_where(SnakeQuery(_Counter), [(_Counter.views, 0)])


def test_update_where_with_limit_raises() -> None:
    """Verifies that a bulk UPDATE with a limit is not supported (it only uses the filter)."""
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    query = SnakeQuery(_Counter).filter(_Counter.id == 1).limit(10)
    with pytest.raises(
        SnakeUnsupportedFeature, match=r"only uses the filter \(WHERE\)"
    ):
        session.update_where(query, [(_Counter.views, 0)])


def test_update_where_with_order_by_raises() -> None:
    """Verifies that a bulk UPDATE with an order_by is not supported."""
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    query = SnakeQuery(_Counter).filter(_Counter.id == 1).order_by(_Counter.id)
    with pytest.raises(
        SnakeUnsupportedFeature, match=r"only uses the filter \(WHERE\)"
    ):
        session.update_where(query, [(_Counter.views, 0)])


def test_update_where_with_include_raises() -> None:
    """Verifies that a bulk UPDATE with an include is not supported."""
    snake_link()
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    query = SnakeQuery(Truck).filter(Truck.model == "Ibiza").include(Truck.maker)
    with pytest.raises(
        SnakeUnsupportedFeature, match=r"only uses the filter \(WHERE\)"
    ):
        session.update_where(query, [(Truck.model, "X")])


def test_update_where_with_deep_filter_rewrites_to_pk_in_subquery() -> None:
    """Verifies that a deep WHERE NO LONGER raises: it is rewritten to `id IN (SELECT ... JOINs ...)`."""
    snake_link()
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    query = SnakeQuery(Truck).filter(Truck.maker.nation.name == "España")
    session.update_where(query, [(Truck.model, "X")])
    sql, params = driver.calls[0]
    assert sql == (
        'UPDATE "public"."trucks" SET "model" = %s WHERE "id" IN ('
        'SELECT t0."id" FROM "public"."trucks" AS t0 '
        'JOIN "public"."makers" AS t1 ON t0."maker_id" = t1."id" '
        'JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id" '
        'WHERE t2."name" = %s)'
    )
    assert params == ("X", "España")


def test_delete_where_emits_sql_and_returns_rowcount() -> None:
    """Verifies that delete_where emits the DELETE with WHERE, passes the params, returns rowcount."""
    driver = _FakeDriver(rowcount=3)
    session = SnakeSession(driver, PostgresDialect())
    affected = session.delete_where(SnakeQuery(_Counter).filter(_Counter.id == 7))
    sql, params = driver.calls[0]
    assert sql == 'DELETE FROM "public"."ww_counters" WHERE "id" = %s'
    assert params == (7,)
    assert affected == 3


def test_delete_where_without_filter_raises() -> None:
    """Verifies the GUARD: a bulk DELETE with no WHERE would wipe the whole table → it raises."""
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    with pytest.raises(
        SnakeUnsupportedFeature,
        match="a DELETE without a WHERE would affect the WHOLE table",
    ):
        session.delete_where(SnakeQuery(_Counter))


def test_delete_where_with_deep_filter_rewrites_to_pk_in_subquery() -> None:
    """Verifies that a DELETE with a deep WHERE NO LONGER raises: rewritten to `id IN (SELECT)`."""
    snake_link()
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    query = SnakeQuery(Truck).filter(Truck.maker.nation.name == "España")
    session.delete_where(query)
    sql, params = driver.calls[0]
    assert sql == (
        'DELETE FROM "public"."trucks" WHERE "id" IN ('
        'SELECT t0."id" FROM "public"."trucks" AS t0 '
        'JOIN "public"."makers" AS t1 ON t0."maker_id" = t1."id" '
        'JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id" '
        'WHERE t2."name" = %s)'
    )
    assert params == ("España",)
