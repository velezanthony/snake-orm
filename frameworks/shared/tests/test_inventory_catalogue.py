"""What the inventory is made OF: the warehouses and the SKUs a stock pair points at.

Every other page in this domain is about what is IN the inventory — a pair, its levels, its
movements. None of them could bring into existence the two things a pair POINTS AT, so the demo
could only ever stock what the seeder had made. `create_warehouse` and `create_sku` were two of the
twelve writes the API could perform and the pages could not, and they were the two with nowhere to
land.

THE WAREHOUSE-WIDE RESERVE LANDS HERE TOO, and for the same reason rather than for tidiness: it
reserves across a WHOLE warehouse's stock in one statement, so it belongs on the screen where a
warehouse is a row. `receive` and `ship` closed by landing on a pair's detail page, which is where a
movement belongs; this one is not about a pair at all.

WHAT IT COSTS: TWO statements, and neither grows with the rows — the warehouses and the SKUs, once
each. A page that counted the stock of every warehouse would be the N+1 the report page already
answers properly, and this page is not the report.
"""

from __future__ import annotations

from datetime import date, time, timedelta, timezone
from decimal import Decimal

from snakeorm import SnakeSession
from snakeorm.debug import capture_queries

from shared.models import SkuKind
from shared.usecases import inventory_usecases as inventory
from shared.usecases.result import Failure
from shared.viewmodels import inventory_viewmodels as viewmodels


def _warehouse(session: SnakeSession, code: str) -> int:
    """One warehouse through the use case, the same door the page uses."""
    warehouse = inventory.create_warehouse(
        session,
        code=code,
        name=f"Warehouse {code}",
        opened_on=date(2020, 3, 14),
        shift_start=time(6, 30),
        cutoff=time(18, 0, tzinfo=timezone(timedelta(hours=1))),
    )
    assert not isinstance(warehouse, Failure), warehouse
    return warehouse.id


def _sku(session: SnakeSession, name: str) -> int:
    """One SKU through the use case."""
    sku = inventory.create_sku(
        session,
        name=name,
        kind=SkuKind.PHYSICAL,
        price=Decimal("10.00"),
        weight_kg=1.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(sku, Failure), sku
    return sku.id


def test_an_empty_catalogue_is_a_page_and_not_a_failure(session: SnakeSession) -> None:
    """With nothing in it the page still draws, and it is the page where making one is the point."""
    page = viewmodels.inventory_catalogue(session)

    assert page["warehouses"] == []
    assert page["skus"] == []


def test_it_lists_the_warehouses_and_the_skus_already_flattened(
    session: SnakeSession,
) -> None:
    """The template gets strings and numbers, never a model. That is what this layer is."""
    _warehouse(session, "MAD")
    _sku(session, "Widget")
    session.commit()

    page = viewmodels.inventory_catalogue(session)

    assert [row["code"] for row in page["warehouses"]] == ["MAD"]
    assert [row["name"] for row in page["skus"]] == ["Widget"]
    assert page["skus"][0]["price"] == "10.00"
    assert isinstance(page["warehouses"][0]["opened_on"], str)


def test_whether_a_warehouse_is_open_travels_as_a_BOOLEAN(
    session: SnakeSession,
) -> None:
    """`active` is a boolean and not a label, because a template wants to branch on it.

    A string somebody might translate is a worse thing to branch on, and a closed warehouse stays a
    row either way: its movements are history that points at it.
    """
    _warehouse(session, "BCN")
    session.commit()

    page = viewmodels.inventory_catalogue(session)

    assert page["warehouses"][0]["active"] is True


def test_it_is_TWO_statements_however_many_rows(session: SnakeSession) -> None:
    """The warehouses and the SKUs, once each. Nothing on this page grows with the data.

    A page that showed how much each warehouse holds would need the report's aggregates, and that
    is the report's job — asking per row here is the N+1 the reporting page exists to not be.
    """
    for index in range(6):
        _warehouse(session, f"W{index}")
        _sku(session, f"SKU {index}")
    session.commit()

    with capture_queries() as collector:
        page = viewmodels.inventory_catalogue(session)

    assert len(page["warehouses"]) == 6
    assert len(page["skus"]) == 6
    assert collector.report().count == 2, collector.report().to_text()
