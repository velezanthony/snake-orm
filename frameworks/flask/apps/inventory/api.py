"""JSON API of the inventory domain: thin endpoints over `shared`.

Every endpoint parses the request, calls the use case with flat parameters and translates the result
into JSON (data -> DTO, `Failure` -> `abort(status)`). There is not one query here, and not one
`commit`: the stock rules —do not ship what is not there, do not receive zero— live in
`shared.usecases` because they are the same rules on the three frameworks.

The composite key surfaces in the ROUTES: a stock row is addressed by
`/warehouses/<id>/stock/<sku_id>`, because neither half identifies it on its own.
"""

from __future__ import annotations

from typing import TypeVar

from datetime import date, time, timedelta
from decimal import Decimal, InvalidOperation

from flask import abort, g, jsonify, request
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from apps import wire
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
from shared.usecases.result import FAILURE_STATUS

T = TypeVar("T")

inventory = Blueprint(
    # `-api` because the plain `inventory` belongs to the PAGES in `urls.py`, the way `blog`/`blog-api`
    # and `auth`/`auth-api` already split. This blueprint held the plain name while the domain had no
    # pages, which worked exactly until it had some: two blueprints cannot share one `url_for` name.
    "inventory-api",
    __name__,
    url_prefix="/api/inventory",
    description="Inventory: warehouses, SKUs and stock with a composite key",
)


def _or_abort(result: T | Failure) -> T:
    """Unwraps a use case's result, or aborts with the status its reason maps to.

    The signature is the whole fix, and it is one type variable long. It used to take `object` and
    answer `object`, so every caller got back something with no type at all and paid for it with a
    `# type: ignore[arg-type]` on the very next line — nine of them in this file. The unwrap was
    THROWING AWAY the type, and the ignores were the receipt.

    `T | Failure` in and `T` out says what the function actually does, and it works because
    `flask.abort()` is `NoReturn`: after the `if`, the checker knows the `Failure` branch cannot
    return, so what is left is exactly the `T` the use case promised.
    """
    if isinstance(result, Failure):
        abort(FAILURE_STATUS.get(result.reason, 400))
    return result


def _int_arg(name: str, default: int) -> int:
    """A query-string integer, falling back rather than raising: the value comes from a URL."""
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


def _optional_warehouse() -> int | None:
    """The `warehouse_id` filter, or `None` when it was not asked for.

    `None` is not a missing value here, it is the WHOLE inventory: the pager and the export both
    narrow to one warehouse when told and answer for every warehouse when not. Anything that is not
    a number reads as absent rather than as a 400, because a filter arriving from a URL is whatever
    somebody typed there and refusing the page teaches nothing.
    """
    raw = request.args.get("warehouse_id")
    return int(raw) if raw is not None and raw.isdigit() else None


@inventory.get("/warehouses")
def list_warehouses() -> ResponseReturnValue:
    """Every warehouse; `?active=1` returns only the open ones."""
    active_only = request.args.get("active") == "1"
    rows = usecases.list_warehouses(g.session, active_only=active_only)
    return jsonify([warehouse_dict(w) for w in rows])


@inventory.get("/warehouses/<int:warehouse_id>")
def get_warehouse(warehouse_id: int) -> ResponseReturnValue:
    """One warehouse, or 404."""
    warehouse = _or_abort(usecases.get_warehouse(g.session, warehouse_id))
    return jsonify(warehouse_dict(warehouse))


@inventory.get("/skus")
def list_skus() -> ResponseReturnValue:
    """Every SKU, with the price EXACT and the thumbnail reduced to its size."""
    return jsonify([sku_dict(s) for s in usecases.list_skus(g.session)])


@inventory.get("/low-stock")
def low_stock() -> ResponseReturnValue:
    """The pairs running out, from the read-only VIEW. The threshold lives in the database."""
    return jsonify([low_stock_dict(r) for r in usecases.low_stock(g.session)])


@inventory.get("/movement-book")
def movement_book() -> ResponseReturnValue:
    """The movement book: the last lines of each origin, duplicates KEPT because they are events."""
    return jsonify(
        [ledger_line_dict(line) for line in usecases.movement_book(g.session)]
    )


@inventory.get("/stats")
def warehouse_stats() -> ResponseReturnValue:
    """Every warehouse with its aggregates, in ONE statement."""
    return jsonify(
        [warehouse_stats_dict(s) for s in usecases.warehouse_stats(g.session)]
    )


@inventory.get("/stock/page")
def paginate_stock() -> ResponseReturnValue:
    """One page of stock together with what the pager needs. TWO statements, whatever the size."""
    return jsonify(
        stock_page_dict(
            usecases.paginate_stock(
                g.session,
                warehouse_id=_optional_warehouse(),
                page=_int_arg("page", 1),
                per_page=_int_arg("per_page", 20),
            )
        )
    )


@inventory.get("/report")
def stock_report() -> ResponseReturnValue:
    """The whole inventory report: annotate, GROUP BY + HAVING, a window, a DISTINCT JOIN and a count."""
    return jsonify(
        stock_report_dict(
            usecases.stock_report(
                g.session,
                minimum_moves=_int_arg("minimum_moves", 2),
                ranking_size=_int_arg("ranking_size", 50),
            )
        )
    )


@inventory.get("/export")
def export_movements() -> ResponseReturnValue:
    """The stock movements as a STREAM, drained into the response.

    Drained HERE and not inside the use case, for the reason `apps/orders/api.py` sets out over its
    own export: the response is one document, and what streaming buys is that the RESULT SET is not.
    """
    movements = usecases.stream_movements(g.session, warehouse_id=_optional_warehouse())
    return jsonify([movement_dict(movement) for movement in movements])


@inventory.get("/warehouses/<int:warehouse_id>/stock/<int:sku_id>")
def get_stock(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """One stock pair with its warehouse and its SKU loaded, in one statement. 404 if it holds nothing.

    The READ of the resource the three writes below already answer for. It was missing, so a client
    could count, correct and delete a pair it had no way of fetching — and the only route that would
    show it to them was an HTML page. A resource one surface can write and cannot read is not one.
    """
    stock = _or_abort(usecases.get_stock(g.session, warehouse_id, sku_id))
    return jsonify(stock_with_relations_dict(stock))


@inventory.get("/warehouses/<int:warehouse_id>/stock")
def stock_of_warehouse(warehouse_id: int) -> ResponseReturnValue:
    """A warehouse's stock with its SKU loaded: one statement, no N+1."""
    rows = _or_abort(usecases.stock_of_warehouse(g.session, warehouse_id))
    return jsonify([stock_dict(row) for row in rows])


@inventory.get("/warehouses/<int:warehouse_id>/stock/movements")
def stock_with_movements(warehouse_id: int) -> ResponseReturnValue:
    """Stock with each row's movements: the to-many over a COMPOSITE foreign key."""
    rows = _or_abort(usecases.stock_with_movements(g.session, warehouse_id))
    return jsonify(
        [
            {**stock_dict(row), "movements": [movement_dict(m) for m in row.movements]}
            for row in rows
        ]
    )


@inventory.get("/warehouses/<int:warehouse_id>/stock/<int:sku_id>/movements")
def movements_of(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """The movements of ONE stock row, addressed by both halves of its key."""
    rows = _or_abort(usecases.movements_of(g.session, warehouse_id, sku_id))
    return jsonify([movement_dict(m) for m in rows])


@inventory.post("/warehouses")
def create_warehouse() -> ResponseReturnValue:
    """Creates a warehouse. `opened_on` and `shift_start` come in as ISO text."""
    body = wire.json_object(request)
    warehouse = _or_abort(
        usecases.create_warehouse(
            g.session,
            code=wire.text(body.get("code")),
            name=wire.text(body.get("name")),
            opened_on=date.fromisoformat(
                wire.text(body.get("opened_on"), "2024-01-01")
            ),
            shift_start=time.fromisoformat(wire.text(body.get("shift_start"), "08:00")),
            cutoff=time.fromisoformat(wire.text(body.get("cutoff"), "18:00+01:00")),
        )
    )
    return jsonify(warehouse_dict(warehouse)), 201


@inventory.post("/skus")
def create_sku() -> ResponseReturnValue:
    """Creates a SKU. The price travels as TEXT so the cent survives the JSON."""
    body = wire.json_object(request)
    try:
        price = Decimal(wire.text(body.get("price"), "0"))
    except InvalidOperation:
        abort(400)
    sku = _or_abort(
        usecases.create_sku(
            g.session,
            name=wire.text(body.get("name")),
            kind=SkuKind(wire.text(body.get("kind"), SkuKind.PHYSICAL.value)),
            price=price,
            weight_kg=wire.real(body.get("weight_kg")),
            lead_time=timedelta(days=wire.integer(body.get("lead_time_days"), 1)),
            attrs=dict(wire.mapping(body.get("attrs"))),
            related_ids=[
                wire.integer(i) for i in wire.sequence(body.get("related_ids"))
            ],
        )
    )
    return jsonify(sku_dict(sku)), 201


@inventory.post("/warehouses/<int:warehouse_id>/stock/<int:sku_id>/receive")
def receive(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """Receives goods into a pair, creating the stock row if it was not there."""
    body = wire.json_object(request)
    stock = _or_abort(
        usecases.receive(
            g.session,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            units=wire.integer(body.get("units")),
        )
    )
    return jsonify(stock_dict(stock))


@inventory.post("/warehouses/<int:warehouse_id>/stock/<int:sku_id>/ship")
def ship(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """Ships goods out. 409 if there are not that many: the rule refuses BEFORE writing."""
    body = wire.json_object(request)
    stock = _or_abort(
        usecases.ship(
            g.session,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            units=wire.integer(body.get("units")),
        )
    )
    return jsonify(stock_dict(stock))


@inventory.put("/warehouses/<int:warehouse_id>/stock/<int:sku_id>")
def count_stock(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """Sets the stock of a pair after a physical count. UPSERT over the composite key."""
    body = wire.json_object(request)
    _or_abort(
        usecases.count_stock(
            g.session,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            on_hand=wire.integer(body.get("on_hand")),
        )
    )
    return jsonify({"warehouse_id": warehouse_id, "sku_id": sku_id})


@inventory.patch("/warehouses/<int:warehouse_id>/stock/<int:sku_id>")
def update_stock(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """Corrects BOTH levels of a pair that already exists. 404 if it is not there.

    `PATCH` and not `PUT`, which is the difference from `count_stock` above spelled in the method:
    that one is an upsert and means "this pair now holds N whether or not it existed", this one edits
    a row. A pair that vanished between the form being drawn and being submitted is a 404, not a
    silent insert of a row nobody asked to create.
    """
    body = wire.json_object(request)
    stock = _or_abort(
        usecases.update_stock(
            g.session,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            on_hand=wire.integer(body.get("on_hand")),
            reserved=wire.integer(body.get("reserved")),
        )
    )
    return jsonify(stock_dict(stock))


@inventory.delete("/warehouses/<int:warehouse_id>/stock/<int:sku_id>")
def remove_stock(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """Deletes a stock pair. 404 if it is not there, 409 if its history would be orphaned.

    The refusal is the interesting half, and it is the same one the delete PAGE gives: the movements
    are the audit trail and the foreign key is RESTRICT, so a pair that has moved gets closed rather
    than deleted. Answering 409 here is what stops the engine from refusing three layers down, from
    inside a commit, with a driver error.
    """
    _or_abort(
        usecases.remove_stock(g.session, warehouse_id=warehouse_id, sku_id=sku_id)
    )
    return "", 204


@inventory.post("/warehouses/<int:warehouse_id>/reserve")
def reserve(warehouse_id: int) -> ResponseReturnValue:
    """Reserves units across the warehouse's whole stock in ONE statement."""
    body = wire.json_object(request)
    touched = _or_abort(
        usecases.reserve(
            g.session, warehouse_id=warehouse_id, units=wire.integer(body.get("units"))
        )
    )
    return jsonify({"rows": touched})
