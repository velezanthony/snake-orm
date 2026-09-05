"""A warehouse that holds nothing holds ZERO units, and the report has to say so.

`warehouse_stats` annotates two correlated aggregates into `WarehouseStats`, whose `total_units` is
declared `int`. A `SUM` over no rows is not zero on any engine: it is NULL. So a warehouse that was
opened this morning and has received nothing comes back with `None` in a field that promises `int` —
and the demos never noticed, because every warehouse the seeder makes gets stock.

WHY IT IS NOT FIXED IN PYTHON. `int(total or 0)` in the executor would silence this one reading and
leave the value wrong everywhere else it is used, because a value only exists in Python AFTER the
statement has run. It cannot be ordered by: NULL sorts first on some engines and last on others, so
"warehouses by units held" would put the empty one at a different end depending on the `.env`. It
cannot be filtered on either — `total > 0` over NULL is not false, it is unknown, and the row
disappears from a `HAVING` instead of failing it.

`COALESCE` puts the zero where the aggregate is computed, so the value is an `int` from the moment
the engine produces it and every downstream use gets the same answer.

WHAT `total_units` MEANS after this. The number of units in the warehouse: zero when there are none,
which is a measurement rather than a missing value. There IS a domain where NULL and zero differ —
"never counted" against "counted, found empty" — and this is not it: `Stock` rows are the count.
"""

from __future__ import annotations

from datetime import date, time, timedelta, timezone
from decimal import Decimal

from snakeorm import SnakeSession

from shared.models import SkuKind
from shared.selectors import inventory_selectors as selectors
from shared.usecases import inventory_usecases as inventory
from shared.usecases.result import Failure


def _empty_warehouse(session: SnakeSession, code: str) -> int:
    """A warehouse opened and never stocked, which is what every warehouse is on day one."""
    warehouse = inventory.create_warehouse(
        session,
        code=code,
        name=f"Warehouse {code}",
        opened_on=date(2020, 3, 14),
        shift_start=time(6, 30),
        cutoff=time(18, 0, tzinfo=timezone(timedelta(hours=1))),
    )
    assert not isinstance(warehouse, Failure), warehouse
    session.commit()
    return warehouse.id


def test_an_empty_warehouse_reports_zero_units_and_not_none(
    session: SnakeSession,
) -> None:
    """The whole point. `total_units` is declared `int`, so it has to BE one.

    Before the `COALESCE` this came back `None` and nothing complained: a dataclass annotation is not
    a runtime check, so the wrong type travelled all the way to a template that renders it as the
    empty string.
    """
    _empty_warehouse(session, "NIL")

    stats = {
        row.warehouse.code: row.total_units
        for row in selectors.warehouse_stats(session)
    }

    assert stats["NIL"] == 0
    assert isinstance(stats["NIL"], int)


def test_the_count_of_skus_was_already_zero_and_stays_zero(
    session: SnakeSession,
) -> None:
    """`sku_count` needed nothing, and the difference between the two is worth keeping visible.

    A `COUNT` over no rows is zero on every engine; a `SUM` over no rows is NULL on every engine.
    They sit in the same annotation and behave differently, which is exactly why one of the two went
    unnoticed.
    """
    _empty_warehouse(session, "NIL")

    stats = {
        row.warehouse.code: row.sku_count for row in selectors.warehouse_stats(session)
    }

    assert stats["NIL"] == 0


def test_a_warehouse_with_stock_still_reports_what_it_holds(
    session: SnakeSession,
) -> None:
    """The `COALESCE` must not touch the case that already worked, which is every other row."""
    warehouse_id = _empty_warehouse(session, "BCN")
    sku = inventory.create_sku(
        session,
        name="Widget",
        kind=SkuKind.PHYSICAL,
        price=Decimal("10.00"),
        weight_kg=1.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(sku, Failure), sku
    counted = inventory.count_stock(
        session, warehouse_id=warehouse_id, sku_id=sku.id, on_hand=7
    )
    assert not isinstance(counted, Failure), counted
    session.commit()

    stats = {
        row.warehouse.code: row.total_units
        for row in selectors.warehouse_stats(session)
    }

    assert stats["BCN"] == 7


def test_the_empty_warehouse_can_be_ORDERED_with_the_rest(
    session: SnakeSession,
) -> None:
    """The reason it is SQL and not Python: a NULL sorts differently depending on the engine.

    With the zero produced by the engine, "the warehouse holding least" is the empty one on all
    three. Patched in Python after the fact, the ordering has already happened and the answer
    depends on the `.env`.
    """
    _empty_warehouse(session, "NIL")
    warehouse_id = _empty_warehouse(session, "BCN")
    sku = inventory.create_sku(
        session,
        name="Widget",
        kind=SkuKind.PHYSICAL,
        price=Decimal("10.00"),
        weight_kg=1.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(sku, Failure), sku
    inventory.count_stock(session, warehouse_id=warehouse_id, sku_id=sku.id, on_hand=7)
    session.commit()

    ordered = selectors.warehouses_by_units_held(session)

    assert [code for code, _ in ordered][:2] == ["NIL", "BCN"]
    assert ordered[0] == ("NIL", 0)
