"""Router of the inventory domain: a thin JSON API over the use cases.

Every endpoint parses the request (Pydantic), calls the use case with flat parameters and translates
the result into JSON (data -> DTO, `Failure` -> HTTPException). Zero queries and zero `commit` here:
the stock rules live in `shared.usecases`, which is why they read the same on the three frameworks.

The composite key shows up in the ROUTES — a stock row is `/warehouses/{id}/stock/{sku_id}` —
because neither half identifies it on its own, and a URL that pretended otherwise would be lying
about the model.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Response
from pydantic import BaseModel

from apps.deps import SessionDep, http_error
from apps.inventory import usecases
from apps.inventory.usecases import Failure
from shared.dto.inventory_dto import (
    ledger_line_dict,
    low_stock_dict,
    movement_dict,
    sku_dict,
    stock_dict,
    stock_page_dict,
    stock_report_dict,
    stock_with_relations_dict,
    warehouse_dict,
    warehouse_stats_dict,
)
from shared.models import SkuKind

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


class WarehouseIn(BaseModel):
    """Body for creating a warehouse."""

    code: str
    name: str
    opened_on: date
    shift_start: time
    # The cutoff carries its OFFSET and the shift start does not. Pydantic parses both into `time`;
    # what tells them apart is whether the text brought a zone, which is the information itself.
    cutoff: time


class SkuIn(BaseModel):
    """Body for creating a SKU. The price is TEXT so the cent survives the JSON."""

    name: str
    kind: SkuKind = SkuKind.PHYSICAL
    price: str
    weight_kg: float = 0.0
    lead_time_days: int = 1
    attrs: dict = {}
    related_ids: list[int] = []


class UnitsIn(BaseModel):
    """Body for a movement: how many units come in or go out."""

    units: int


class QuantityIn(BaseModel):
    """Body for a physical count: how many there ARE, not how many changed."""

    on_hand: int


class LevelsIn(BaseModel):
    """Body for a correction: BOTH levels of a pair that already exists.

    Separate from `QuantityIn` and not a superset of it, because the two operations mean different
    things: a count is an upsert over `on_hand`, and this edits a row somebody opened — including
    what is reserved, which a count never touches.
    """

    on_hand: int
    reserved: int


@router.get("/warehouses")
async def list_warehouses(
    session: SessionDep, active: bool = False
) -> list[dict[str, object]]:
    """Every warehouse; `?active=true` returns only the open ones."""
    return [
        warehouse_dict(w)
        for w in await usecases.list_warehouses(session, active_only=active)
    ]


@router.get("/warehouses/{warehouse_id}")
async def get_warehouse(warehouse_id: int, session: SessionDep) -> dict[str, object]:
    """One warehouse. 404 if it does not exist."""
    result = await usecases.get_warehouse(session, warehouse_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return warehouse_dict(result)


@router.get("/skus")
async def list_skus(session: SessionDep) -> list[dict[str, object]]:
    """Every SKU, with its ten declared types."""
    return [sku_dict(s) for s in await usecases.list_skus(session)]


@router.get("/low-stock")
async def low_stock(session: SessionDep) -> list[dict[str, object]]:
    """The pairs running out, from the read-only VIEW. The threshold lives in the database."""
    return [low_stock_dict(r) for r in await usecases.low_stock(session)]


@router.get("/movement-book")
async def movement_book(session: SessionDep) -> list[dict[str, object]]:
    """The movement book: the last lines of each origin, duplicates KEPT because they are events."""
    return [ledger_line_dict(line) for line in await usecases.movement_book(session)]


@router.get("/stats")
async def warehouse_stats(session: SessionDep) -> list[dict[str, object]]:
    """Every warehouse with its aggregates, in ONE statement."""
    return [warehouse_stats_dict(s) for s in await usecases.warehouse_stats(session)]


@router.get("/stock/page")
async def paginate_stock(
    session: SessionDep,
    warehouse_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict[str, object]:
    """One page of stock together with what the pager needs. TWO statements, whatever the size.

    `warehouse_id` is optional and its absence is the WHOLE inventory rather than a missing value,
    which is why the pager hangs off `/stock` and not off a warehouse: there is nothing for it to
    be a sub-resource of.
    """
    return stock_page_dict(
        await usecases.paginate_stock(
            session, warehouse_id=warehouse_id, page=page, per_page=per_page
        )
    )


@router.get("/report")
async def stock_report(
    session: SessionDep, minimum_moves: int = 2, ranking_size: int = 50
) -> dict[str, object]:
    """The whole inventory report: annotate, GROUP BY + HAVING, a window, a DISTINCT JOIN and a count."""
    return stock_report_dict(
        await usecases.stock_report(
            session, minimum_moves=minimum_moves, ranking_size=ranking_size
        )
    )


@router.get("/export")
async def export_movements(
    session: SessionDep, warehouse_id: int | None = None
) -> list[dict[str, object]]:
    """The stock movements as a STREAM, drained into the response.

    The stream is what the use case hands back and it is drained HERE rather than inside it, for the
    reason `apps/orders/urls.py` sets out over its own export: the response is one document, so it
    exists whole whatever the read did, and what streaming buys is that the RESULT SET never does.

    The `await` in front of the `async for` is not waiting on anything: `stream_movements` is a
    coroutine because `test_async_mirror.py` demands the whole package be, and `AsyncSession.iterate`
    hands the iterator back immediately. `shared/aio/inventory_usecases.py` says so at length.
    """
    return [
        movement_dict(movement)
        async for movement in await usecases.stream_movements(
            session, warehouse_id=warehouse_id
        )
    ]


@router.get("/warehouses/{warehouse_id}/stock")
async def stock_of_warehouse(
    warehouse_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """A warehouse's stock with its SKU loaded: one statement, no N+1."""
    result = await usecases.stock_of_warehouse(session, warehouse_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return [stock_dict(row) for row in result]


@router.get("/warehouses/{warehouse_id}/stock/movements")
async def stock_with_movements(
    warehouse_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """Stock with each row's movements: the to-many over a COMPOSITE foreign key."""
    result = await usecases.stock_with_movements(session, warehouse_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return [
        {**stock_dict(row), "movements": [movement_dict(m) for m in row.movements]}
        for row in result
    ]


@router.get("/warehouses/{warehouse_id}/stock/{sku_id}/movements")
async def movements_of(
    warehouse_id: int, sku_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """The movements of ONE stock row, addressed by both halves of its key."""
    result = await usecases.movements_of(session, warehouse_id, sku_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return [movement_dict(m) for m in result]


@router.get("/warehouses/{warehouse_id}/stock/{sku_id}")
async def get_stock(
    warehouse_id: int, sku_id: int, session: SessionDep
) -> dict[str, object]:
    """One stock pair with its warehouse and its SKU loaded, in one statement. 404 if it holds nothing.

    The READ of the resource the three writes below already answer for. It was missing, so a client
    could count, correct and delete a pair it had no way of fetching — and the only route that would
    show it to them was an HTML page in another demo. A resource one surface can write and cannot
    read is not a resource.

    It is declared AFTER `stock_with_movements`, and that is routing rather than tidiness: Starlette
    takes the first pattern that matches the path, so `{sku_id}` sitting above `/stock/movements`
    would swallow it and answer 422 for a route that exists.
    """
    result = await usecases.get_stock(session, warehouse_id, sku_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return stock_with_relations_dict(result)


@router.post("/warehouses", status_code=201)
async def create_warehouse(
    payload: WarehouseIn, session: SessionDep
) -> dict[str, object]:
    """Create a warehouse."""
    result = await usecases.create_warehouse(
        session,
        code=payload.code,
        name=payload.name,
        opened_on=payload.opened_on,
        shift_start=payload.shift_start,
        cutoff=payload.cutoff,
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return warehouse_dict(result)


@router.post("/skus", status_code=201)
async def create_sku(payload: SkuIn, session: SessionDep) -> dict[str, object]:
    """Create a SKU."""
    result = await usecases.create_sku(
        session,
        name=payload.name,
        kind=payload.kind,
        price=Decimal(payload.price),
        weight_kg=payload.weight_kg,
        lead_time=timedelta(days=payload.lead_time_days),
        attrs=payload.attrs,
        related_ids=payload.related_ids,
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return sku_dict(result)


@router.post("/warehouses/{warehouse_id}/stock/{sku_id}/receive")
async def receive(
    warehouse_id: int, sku_id: int, payload: UnitsIn, session: SessionDep
) -> dict[str, object]:
    """Receive goods into a pair, creating the stock row if it was not there."""
    result = await usecases.receive(
        session, warehouse_id=warehouse_id, sku_id=sku_id, units=payload.units
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return stock_dict(result)


@router.post("/warehouses/{warehouse_id}/stock/{sku_id}/ship")
async def ship(
    warehouse_id: int, sku_id: int, payload: UnitsIn, session: SessionDep
) -> dict[str, object]:
    """Ship goods out. 409 if there are not that many: the rule refuses BEFORE writing."""
    result = await usecases.ship(
        session, warehouse_id=warehouse_id, sku_id=sku_id, units=payload.units
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return stock_dict(result)


@router.put("/warehouses/{warehouse_id}/stock/{sku_id}")
async def count_stock(
    warehouse_id: int, sku_id: int, payload: QuantityIn, session: SessionDep
) -> dict[str, object]:
    """Set the stock of a pair after a physical count. UPSERT over the composite key."""
    result = await usecases.count_stock(
        session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=payload.on_hand
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return {"warehouse_id": warehouse_id, "sku_id": sku_id}


@router.patch("/warehouses/{warehouse_id}/stock/{sku_id}")
async def update_stock(
    warehouse_id: int, sku_id: int, payload: LevelsIn, session: SessionDep
) -> dict[str, object]:
    """Correct BOTH levels of a pair that already exists. 404 if it is not there.

    `PATCH` and not `PUT`, which is the difference from `count_stock` above spelled in the method:
    that one is an upsert and means "this pair now holds N whether or not it existed", this one edits
    a row. A pair that vanished between the form being drawn and being submitted is a 404, not a
    silent insert of a row nobody asked to create.
    """
    result = await usecases.update_stock(
        session,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        on_hand=payload.on_hand,
        reserved=payload.reserved,
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return stock_dict(result)


@router.delete("/warehouses/{warehouse_id}/stock/{sku_id}", status_code=204)
async def remove_stock(warehouse_id: int, sku_id: int, session: SessionDep) -> Response:
    """Delete a stock pair. 404 if it is not there, 409 if its history would be orphaned.

    The refusal is the interesting half, and it is the same one the delete PAGE gives: the movements
    are the audit trail and the foreign key is RESTRICT, so a pair that has moved gets closed rather
    than deleted. Answering 409 here is what stops the engine from refusing three layers down, from
    inside a commit, with a driver error.
    """
    result = await usecases.remove_stock(
        session, warehouse_id=warehouse_id, sku_id=sku_id
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return Response(status_code=204)


@router.post("/warehouses/{warehouse_id}/reserve")
async def reserve(
    warehouse_id: int, payload: UnitsIn, session: SessionDep
) -> dict[str, object]:
    """Reserve units across the warehouse's whole stock in ONE statement."""
    result = await usecases.reserve(
        session, warehouse_id=warehouse_id, units=payload.units
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return {"rows": result}
