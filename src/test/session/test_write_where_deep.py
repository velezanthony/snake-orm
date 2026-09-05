"""BULK writing with a WHERE that crosses a relation: rewritten to `pk IN (subquery)`.

An `update_where`/`delete_where` whose filter navigates a relation does not fit in a flat WHERE over
the base table (the filter columns live in joined tables). Instead of `UPDATE ... FROM` (Postgres
jargon), it is REWRITTEN into a subquery over the PK: the subquery is a SELECT of the PK with the
JOINs of the deep paths (the SAME machinery as a normal SELECT), and the outer WHERE ends up as
`<pk> IN (subquery)`. A composite PK uses the row constructor `(a, b) IN (SELECT a, b ...)`.

It is tested with a FAKE driver (no database): the EXACT SQL and the order of the params (the SET
goes first, the subquery continues the numbering). A SET that navigates a relation makes NO sense
and raises.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.decorators import snake_model
from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.fields import SnakeColumn, SnakeToOne, snake_int, snake_str, snake_to_one

from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.deep_domain import Truck


@snake_model(table="dw_warehouses")
class Warehouse(SnakeModel):
    """Parent with a simple PK: the destination of the deep navigation from Crate."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="dw_crates")
class Crate(SnakeModel):
    """Child with a COMPOSITE PK (region, code) and an FK to Warehouse: tests the tuple-in."""

    region: SnakeColumn[str] = snake_str(primary_key=True)
    code: SnakeColumn[int] = snake_int(primary_key=True)
    warehouse_id: SnakeColumn[int] = snake_int()
    weight: SnakeColumn[int] = snake_int()
    warehouse: SnakeToOne[Warehouse] = snake_to_one(warehouse_id)


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


def test_update_where_one_hop_deep_rewrites_to_pk_in_subquery() -> None:
    """A ONE-hop WHERE (`Truck.maker.name`) emits `id IN (SELECT ... with a JOIN ... WHERE ...)`."""
    snake_link()
    driver = _FakeDriver(rowcount=4)
    session = SnakeSession(driver, PostgresDialect())
    affected = session.update_where(
        SnakeQuery(Truck).filter(Truck.maker.name == "SEAT"), [(Truck.model, "X")]
    )
    sql, params = driver.calls[0]
    assert sql == (
        'UPDATE "public"."trucks" SET "model" = %s WHERE "id" IN ('
        'SELECT t0."id" FROM "public"."trucks" AS t0 '
        'JOIN "public"."makers" AS t1 ON t0."maker_id" = t1."id" '
        'WHERE t1."name" = %s)'
    )
    assert params == ("X", "SEAT")
    assert affected == 4


def test_update_where_two_hops_deep_chains_both_joins() -> None:
    """A TWO-hop WHERE (`Truck.maker.nation.name`) chains both JOINs together (t1, t2)."""
    snake_link()
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.update_where(
        SnakeQuery(Truck).filter(Truck.maker.nation.name == "España"),
        [(Truck.model, "X")],
    )
    sql, params = driver.calls[0]
    assert sql == (
        'UPDATE "public"."trucks" SET "model" = %s WHERE "id" IN ('
        'SELECT t0."id" FROM "public"."trucks" AS t0 '
        'JOIN "public"."makers" AS t1 ON t0."maker_id" = t1."id" '
        'JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id" '
        'WHERE t2."name" = %s)'
    )
    assert params == ("X", "España")


def test_delete_where_deep_rewrites_to_pk_in_subquery() -> None:
    """A DELETE with a deep WHERE emits `DELETE ... WHERE id IN (SELECT id FROM ... JOINs ...)`."""
    snake_link()
    driver = _FakeDriver(rowcount=1)
    session = SnakeSession(driver, PostgresDialect())
    affected = session.delete_where(
        SnakeQuery(Truck).filter(Truck.maker.nation.name == "España")
    )
    sql, params = driver.calls[0]
    assert sql == (
        'DELETE FROM "public"."trucks" WHERE "id" IN ('
        'SELECT t0."id" FROM "public"."trucks" AS t0 '
        'JOIN "public"."makers" AS t1 ON t0."maker_id" = t1."id" '
        'JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id" '
        'WHERE t2."name" = %s)'
    )
    assert params == ("España",)
    assert affected == 1


def test_update_where_deep_with_composite_pk_uses_tuple_in() -> None:
    """With a COMPOSITE PK the outer WHERE uses the row constructor `(region, code) IN (SELECT)`."""
    snake_link()
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.update_where(
        SnakeQuery(Crate).filter(Crate.warehouse.name == "Central"),
        [(Crate.weight, 0)],
    )
    sql, params = driver.calls[0]
    assert sql == (
        'UPDATE "public"."dw_crates" SET "weight" = %s '
        'WHERE ("region", "code") IN ('
        'SELECT t0."region", t0."code" FROM "public"."dw_crates" AS t0 '
        'JOIN "public"."dw_warehouses" AS t1 ON t0."warehouse_id" = t1."id" '
        'WHERE t1."name" = %s)'
    )
    assert params == (0, "Central")


def test_update_where_arithmetic_set_and_deep_where_keep_param_order() -> None:
    """The arithmetic SET consumes the FIRST param; the deep subquery continues the numbering."""
    snake_link()
    driver = _FakeDriver()
    session = SnakeSession(driver, PostgresDialect())
    session.update_where(
        SnakeQuery(Crate).filter(Crate.warehouse.name == "Central"),
        [(Crate.weight, Crate.weight + 5)],
    )
    sql, params = driver.calls[0]
    assert sql == (
        'UPDATE "public"."dw_crates" SET "weight" = ("weight" + %s) '
        'WHERE ("region", "code") IN ('
        'SELECT t0."region", t0."code" FROM "public"."dw_crates" AS t0 '
        'JOIN "public"."dw_warehouses" AS t1 ON t0."warehouse_id" = t1."id" '
        'WHERE t1."name" = %s)'
    )
    assert params == (5, "Central")  # SET (5) first, WHERE ("Central") afterwards


def test_update_where_with_deep_set_key_raises() -> None:
    """A SET navigating a relation (`Truck.maker.nation.id`) cannot be assigned → it raises."""
    snake_link()
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    with pytest.raises(
        SnakeUnsupportedFeature, match="uses direct columns of the table"
    ):
        session.update_where(
            SnakeQuery(Truck).filter(Truck.maker.name == "SEAT"),
            [(Truck.maker.nation.id, 1)],
        )


def test_update_where_with_deep_set_value_raises() -> None:
    """A SET VALUE navigating a relation (`Truck.maker.nation.id`) makes no sense either → raises."""
    snake_link()
    session = SnakeSession(_FakeDriver(), PostgresDialect())
    with pytest.raises(
        SnakeUnsupportedFeature, match="columns/arithmetic of the base table"
    ):
        session.update_where(
            SnakeQuery(Truck).filter(Truck.maker.name == "SEAT"),
            [(Truck.model, Truck.maker.nation.id)],
        )
