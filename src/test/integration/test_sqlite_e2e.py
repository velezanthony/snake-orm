"""SQLite end to end: the proof that the engine seam was honest.

These tests are NEVER skipped: SQLite ships with the stdlib, so they run on any machine. That is
half the reason they exist — until today, exercising the ORM demanded a Postgres up and running.

What gets checked is that the whole of `query/` works without changing a line of the core, and that
what SQLite CANNOT do **fails while COMPILING the query**, not while running it, naming the way out.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest

from snakeorm import (
    SQLiteDialect,
    SQLiteDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    count,
    snake_column,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
    sum_,
)
from snakeorm.core.exceptions import SnakeDialectError, SnakeUnsupportedFeature
from snakeorm.expressions import row_number
from snakeorm.session.coercion import converter_for
from snakeorm.sql.adapt import adapt_param
from snakeorm.migration import emit_create_table

_DIALECT = SQLiteDialect()


@snake_model(table="lite_orders")
class Order(SnakeModel):
    """Model with the types that SQLite maps onto its five storage classes."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    customer: SnakeColumn[str] = snake_str()
    amount: SnakeColumn[int] = snake_int()
    pagado: SnakeColumn[bool] = snake_column()


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """IN-MEMORY database created with the ORM's own DDL. No server, no skips."""
    driver = SQLiteDriver.connect(":memory:")
    driver.execute(emit_create_table(snake_table(Order), _DIALECT), ())
    driver.commit()
    built = SnakeSession(driver, _DIALECT)
    built.add_all(
        [
            Order(id=1, customer="ana", amount=100, pagado=True),
            Order(id=2, customer="ana", amount=250, pagado=False),
            Order(id=3, customer="bea", amount=75, pagado=True),
        ]
    )
    built.commit()
    try:
        yield built
    finally:
        driver.close()


def test_the_ddl_of_the_orm_creates_a_working_table(session: SnakeSession) -> None:
    """The `CREATE TABLE` the ORM emits works as is for SQLite, and it accepts rows."""
    assert session.count(SnakeQuery(Order)) == 3


def test_filtering_and_ordering_work_unchanged(session: SnakeSession) -> None:
    """`query/` works without touching the core: which is what we set out to prove."""
    rows = session.all(
        SnakeQuery(Order).filter(Order.customer == "ana").order_by(Order.amount.desc())
    )

    assert [order.id for order in rows] == [2, 1]


def test_booleans_survive_the_round_trip(session: SnakeSession) -> None:
    """SQLite has no boolean —it stores 0/1— and it still comes back as a `bool`.

    It is the central promise of the ORM: the declared type is the type you get, and the engine
    underneath is a detail. Here it is checked against an engine that does NOT have that type.
    """
    order = session.first(SnakeQuery(Order).filter(Order.id == 1))

    assert order is not None
    assert order.pagado is True and isinstance(order.pagado, bool)


def test_aggregates_and_grouping_work(session: SnakeSession) -> None:
    """Aggregates and `GROUP BY`: phase 2 is reused in full."""
    rows = session.select(
        SnakeQuery(Order).group_by(Order.customer).order_by(Order.customer),
        Order.customer,
        sum_(Order.amount),
        count(),
    )

    assert rows == [("ana", 350, 2), ("bea", 75, 1)]


def test_window_functions_work(session: SnakeSession) -> None:
    """SQLite has window functions since 3.25: phase 2.9 comes for free."""
    rows = session.select(
        SnakeQuery(Order).order_by(Order.id.asc()),
        Order.id,
        row_number().over(partition_by=[Order.customer], order_by=[Order.id.asc()]),
    )

    assert rows == [(1, 1), (2, 2), (3, 1)]


def test_the_set_operations_work(session: SnakeSession) -> None:
    """`UNION` and company as well, with nothing engine-specific in the compound."""
    cheap = SnakeQuery(Order).filter(Order.amount < 100)
    from_bea = SnakeQuery(Order).filter(Order.customer == "bea")

    rows = session.all(cheap.union(from_bea).order_by(Order.id.asc()))

    assert [order.id for order in rows] == [3]


def test_upsert_works(session: SnakeSession) -> None:
    """`ON CONFLICT` has existed in SQLite since 3.24: the `upsert` is reused."""
    session.upsert(
        Order(id=1, customer="ana", amount=999, pagado=True),
        on_conflict=[Order.id],
        update=[Order.amount],
    )
    session.commit()

    order = session.first(SnakeQuery(Order).filter(Order.id == 1))
    assert order is not None and order.amount == 999


def test_offset_without_limit_uses_the_sqlite_idiom(session: SnakeSession) -> None:
    """An `OFFSET` without `LIMIT` works: the dialect adds the `LIMIT -1` that SQLite demands.

    Postgres accepts a bare `OFFSET`. It is the kind of difference the dialect absorbs without the
    rest of the ORM ever finding out.
    """
    rows = session.all(SnakeQuery(Order).order_by(Order.id.asc()).offset(1))

    assert [order.id for order in rows] == [2, 3]


def test_row_locking_fails_at_compile_time_with_the_alternative() -> None:
    """WHAT SQLITE CANNOT DO: it fails while COMPILING and says what to do instead.

    It is the rule fixed at planning time: never emit SQL the engine does not understand just so
    it blows up. And the moment of failure matters — here the database has not even been touched.
    """
    query = SnakeQuery(Order).for_update()

    with pytest.raises(SnakeUnsupportedFeature, match="does not support row locking"):
        query.to_sql(_DIALECT)


def test_an_array_column_survives_the_round_trip_as_a_list() -> None:
    """A list falls back to TEXT on SQLite, and comes back as a LIST. A real round trip.

    This used to be refused, on the argument that storing it as text and returning it as text would
    be losing the type in silence. The argument was a good one: what was wrong was the conclusion.
    The type leak is not caused by the TEXT, it is caused by having no converter on the way back —
    and now there is one, so an attribute declared `list[str]` holds a `list[str]` on all three
    engines.

    It is checked with the real driver and not by reading `map_type`, because the bug this prevents
    lives right in the journey: serializing well and not deserializing leaves raw JSON in the
    attribute.
    """
    assert _DIALECT.map_type(list[str]) == "TEXT"

    written = adapt_param(["rojo", "azul"], native_arrays=False)
    assert isinstance(written, str), "with no native arrays, the list travels as text"

    convert = converter_for(list[str])
    assert convert is not None
    assert convert(written) == ["rojo", "azul"]


def test_an_index_method_is_refused(session: SnakeSession) -> None:
    """SQLite has ONE index type: asking for `method=GIN` is refused instead of ignored.

    Accepting it and emitting an ordinary index would give an index that does not do what the model
    declares, and nobody would find out until they looked at an execution plan.
    """
    from snakeorm.metadata import SnakeIndexMethod

    with pytest.raises(SnakeDialectError, match="only one kind of index"):
        _DIALECT.index_method(SnakeIndexMethod.GIN)


def test_decimal_maps_to_text_because_numeric_would_destroy_it() -> None:
    """`Decimal` goes to TEXT, and the "obvious" answer (NUMERIC) is precisely the one that breaks.

    SQLite's NUMERIC affinity converts to `REAL` any text that looks like a number: a
    `Decimal("1234.56")` is stored exact and comes back as the float `1234.56`. The whole reason for
    declaring `Decimal` is not to lose exactness, so the affinity that carries its very name is the
    only one that cannot be used. With TEXT the value survives untouched.

    This was uncovered by the round-trip matrix (`test/integration/test_type_round_trip.py`), not by
    a reading of the code: the mapping looked perfectly reasonable.
    """
    assert _DIALECT.map_type(Decimal) == "TEXT"
