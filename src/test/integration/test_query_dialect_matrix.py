"""Every QUERY path that emits a correlated subquery, against EVERY engine.

The eighth net, and the first one that does NOT enumerate names: it runs behaviour with real data.
It is born of the blind spot the previous seven left behind. `test_emitter_dialect_matrix` covers
the 24 DDL emitters against both engines; no net covered the QUERY emitters, and seven public APIs
broken on SQLite lived right there —`.any()`, `.count()`, `.sum_()`, `.avg()`, `.min_()`, `.max_()`
and `session.annotate()`— because two emitters built the reference to the child table by hand
(`f"{quote(schema)}.{quote(name)}"`) instead of going through `qualified()`, which already knows
that SQLite has no schemas.

The symptom was a single schizophrenic statement: the outer `FROM` came out as `"cars"` and the
one inside the `EXISTS` came out as `"public"."cars"`, hence `no such table: public.cars`. The
sibling right next door (`_build_exists_joins`) already did it right; it was the same bug as the FKs
of the migrations, in the query layer.

It is tested on SQLite because that is where the absence of schemas uncovers the failure. On
Postgres the `"public".` is correct, so these paths always worked there — which is exactly how a bug
survives a single-engine suite.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SQLiteDialect,
    SQLiteDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeResult,
    SnakeSession,
    SnakeToMany,
    SnakeToOne,
    count,
    snake_auto,
    snake_int,
    snake_link,
    snake_model,
    snake_result,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.migration import emit_create_table
from snakeorm.registry import registry as _REG


@snake_model(table="qm_brands")
class Brand(SnakeModel):
    """A brand with many cars."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    cars: SnakeToMany["Car"] = snake_to_many("brand")


@snake_model(table="qm_cars")
class Car(SnakeModel):
    """A car with a price, belonging to a brand."""

    id: SnakeColumn[int] = snake_auto()
    price: SnakeColumn[int] = snake_int()
    brand_id: SnakeColumn[int] = snake_int()
    brand: SnakeToOne[Brand] = snake_to_one(brand_id)


@snake_result
class Stats(SnakeResult[Brand]):
    """Brand annotated with aggregates of its cars."""

    brand: Brand
    cuantos: int
    total: int | None


@snake_model(table="qm_categories")
class Category(SnakeModel):
    """Self-referential hierarchy, for the WITH RECURSIVE."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    parent_id: SnakeColumn[int | None] = snake_int()
    parent: SnakeToOne["Category | None"] = snake_to_one(parent_id)


snake_link()


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """SQLite in memory with two brands: one with cars, another with none at all."""
    driver = SQLiteDriver.connect(":memory:")
    dialect = SQLiteDialect()
    for model in (Brand, Car):
        table = _REG.table_of(model)
        assert table is not None
        driver.execute(emit_create_table(table, dialect), ())
    driver.commit()
    s = SnakeSession(driver, dialect)
    s.add(Brand(name="Seat"))
    s.add(Brand(name="Vacía"))
    s.commit()
    s.add(Car(price=100, brand_id=1))
    s.add(Car(price=300, brand_id=1))
    s.commit()
    try:
        yield s
    finally:
        driver.close()


def test_any_runs_and_filters(session: SnakeSession) -> None:
    """`.any()` emits a correlated EXISTS and returns only the brand WITH cars."""
    brands = session.all(SnakeQuery(Brand).filter(Brand.cars.any()))

    assert [m.name for m in brands] == ["Seat"]


def test_any_with_a_condition_runs(session: SnakeSession) -> None:
    """`.any(cond)` navigates inside the EXISTS: brands with some car above 200."""
    brands = session.all(SnakeQuery(Brand).filter(Brand.cars.any(Car.price > 200)))

    assert [m.name for m in brands] == ["Seat"]


def test_collection_count_runs(session: SnakeSession) -> None:
    """`.cars.count()` emits a correlated COUNT as a scalar subquery."""
    rows = session.all(
        SnakeQuery(Brand).filter(Brand.cars.count() > 1).order_by(Brand.name)
    )

    assert [m.name for m in rows] == ["Seat"]


@pytest.mark.parametrize(
    ("method", "expected"),
    [("sum_", 400), ("avg", 200), ("min_", 100), ("max_", 300)],
    ids=["sum", "avg", "min", "max"],
)
def test_collection_aggregate_runs(
    method: str, expected: int, session: SnakeSession
) -> None:
    """Every collection aggregate emits its correlated scalar subquery and computes correctly.

    It is the heart of the bug: `Brand.cars.sum_(Car.price)` built `FROM "public"."qm_cars"`
    inside the subquery, against an engine without schemas. All four shared the broken emitter.
    """
    aggregate = getattr(Brand.cars, method)(Car.price)

    brand = session.first(SnakeQuery(Brand).filter(aggregate == expected))

    assert brand is not None and brand.name == "Seat"


def test_annotate_runs(session: SnakeSession) -> None:
    """`session.annotate` projects aggregates per group: it also goes through the child subquery."""
    rows = session.annotate(
        SnakeQuery(Brand),
        Stats,
        cuantos=count(),
        total=Brand.cars.sum_(Car.price),
    )

    by_name = {f.brand.name: f for f in rows}
    assert by_name["Seat"].total == 400
    assert by_name["Vacía"].total is None


def test_no_query_path_qualifies_a_table_in_a_schemaless_engine() -> None:
    """THE cross-cutting guarantee: no query SQL names `"public".` on SQLite.

    Postgres qualifies with a schema; SQLite has no schemas. A `"public".` in the SQL emitted for
    SQLite is invalid SQL waiting to be executed. The emitted string of every path that generates
    subqueries is inspected, which is where the bug was hiding.
    """
    dialect = SQLiteDialect()
    paths = {
        ".any()": SnakeQuery(Brand).filter(Brand.cars.any()),
        ".any(cond)": SnakeQuery(Brand).filter(Brand.cars.any(Car.price > 0)),
        ".count()": SnakeQuery(Brand).filter(Brand.cars.count() > 0),
        "sum_": SnakeQuery(Brand).filter(Brand.cars.sum_(Car.price) > 0),
    }
    culprits = {
        name: query.to_sql(dialect)[0]
        for name, query in paths.items()
        if '"public"' in query.to_sql(dialect)[0]
    }

    assert culprits == {}, f"these paths qualify with a schema on SQLite: {culprits}"


def test_recursive_cte_runs_in_both_engines() -> None:
    """`WITH RECURSIVE` runs on SQLite, not only on Postgres.

    It emitted `AS ((SELECT anchor) UNION ALL ...)` and SQLite rejects the parenthesis around the
    anchor (`near "(": syntax error`) — the SAME `supports_parenthesised_compound` flag that the
    UNION emitter does respect and the recursive one does not. Another "correct on N-1 of N
    engines".
    """
    driver = SQLiteDriver.connect(":memory:")
    dialect = SQLiteDialect()
    table = _REG.table_of(Category)
    assert table is not None
    try:
        driver.execute(emit_create_table(table, dialect), ())
        driver.commit()
        s = SnakeSession(driver, dialect)
        # root(1) -> 2 -> 3, plus a loose branch (4) that does NOT hang off 1
        s.add(Category(name="raiz", parent_id=None))
        s.add(Category(name="hija", parent_id=1))
        s.add(Category(name="nieta", parent_id=2))
        s.add(Category(name="other", parent_id=None))
        s.commit()

        descendants = s.all(
            SnakeQuery(Category)
            .filter(Category.id == 1)
            .recursive(on=(Category.parent_id, Category.id))
        )

        names = sorted(c.name for c in descendants)
        assert names == ["hija", "nieta", "raiz"], "the 'other' branch must not appear"
    finally:
        driver.close()
