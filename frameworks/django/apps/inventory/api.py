"""Thin JSON API for the inventory domain: DRF (`@api_view`) over `shared`.

Thin views: they parse the request, call the use case with flat parameters and serialize with the
shared DTOs (data) or map the `Failure` to its status (error). Zero queries and zero `commit` here —
the stock rules live in `shared.usecases`, so the three demos refuse the same shipment for the same
reason. The session is hung on `request.snake_session` by `SnakeSessionMiddleware`.

Since Django routes a URL to ONE view, the routes that are a GET list and a POST create at the same
path are handled by a single view dispatching on the method.

The composite key surfaces in the ROUTES: a stock row is `warehouses/<id>/stock/<sku_id>`, because
neither half identifies it on its own.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal, InvalidOperation

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


from apps import wire
from apps.session import snake_session
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


_session = snake_session


def _int(request: Request, name: str, default: int) -> int:
    """A query-string integer, falling back rather than raising: the value comes from a URL."""
    try:
        return int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        return default


def _optional_warehouse(request: Request) -> int | None:
    """The `warehouse_id` filter, or `None` when it was not asked for.

    `None` is not a missing value here, it is the WHOLE inventory: the pager and the export both
    narrow to one warehouse when told and answer for every warehouse when not. Anything that is not
    a number reads as absent rather than as a 400, because a filter arriving from a URL is whatever
    somebody typed there and refusing the page teaches nothing.
    """
    raw = request.query_params.get("warehouse_id")
    return int(raw) if raw is not None and raw.isdigit() else None


def _refusal(failure: Failure) -> Response:
    """The response a refused use case turns into: its reason, with the status the reason maps to.

    It takes the `Failure` and not the result, which is the whole difference. The old helper took the
    result and answered `Response | None`, so the call site read
    `return _failed(result) or Response(stock_dict(result))` — one line, and unTYPEABLE: the `or`
    proves nothing about `result`, which stays `Stock | Failure` into a function that wants a `Stock`.
    That is what the nine `# type: ignore` of this file were paying for. An `isinstance` at the call
    site costs two lines and narrows for real.
    """
    return Response(
        {"detail": failure.reason}, status=FAILURE_STATUS.get(failure.reason, 400)
    )


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def warehouses(request: Request) -> Response:
    """GET: every warehouse (`?active=1` only the open ones). POST: create one."""
    session = _session(request)
    if request.method == "GET":
        active_only = request.query_params.get("active") == "1"
        rows = usecases.list_warehouses(session, active_only=active_only)
        return Response([warehouse_dict(w) for w in rows])
    body = wire.json_object(request)
    result = usecases.create_warehouse(
        session,
        code=wire.text(body.get("code")),
        name=wire.text(body.get("name")),
        opened_on=date.fromisoformat(wire.text(body.get("opened_on"), "2024-01-01")),
        shift_start=time.fromisoformat(wire.text(body.get("shift_start"), "08:00")),
        cutoff=time.fromisoformat(wire.text(body.get("cutoff"), "18:00+01:00")),
    )
    if isinstance(result, Failure):
        return _refusal(result)
    return Response(warehouse_dict(result), status=201)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def get_warehouse(request: Request, warehouse_id: int) -> Response:
    """One warehouse. 404 if it does not exist."""
    result = usecases.get_warehouse(_session(request), warehouse_id)
    if isinstance(result, Failure):
        return _refusal(result)
    return Response(warehouse_dict(result))


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def skus(request: Request) -> Response:
    """GET: every SKU with its ten declared types. POST: create one."""
    session = _session(request)
    if request.method == "GET":
        return Response([sku_dict(s) for s in usecases.list_skus(session)])
    body = wire.json_object(request)
    try:
        price = Decimal(wire.text(body.get("price"), "0"))
    except InvalidOperation:
        return Response({"detail": "missing_fields"}, status=400)
    result = usecases.create_sku(
        session,
        name=wire.text(body.get("name")),
        kind=SkuKind(wire.text(body.get("kind"), SkuKind.PHYSICAL.value)),
        price=price,
        weight_kg=wire.real(body.get("weight_kg")),
        lead_time=timedelta(days=wire.integer(body.get("lead_time_days"), 1)),
        attrs=dict(wire.mapping(body.get("attrs"))),
        related_ids=[wire.integer(i) for i in wire.sequence(body.get("related_ids"))],
    )
    if isinstance(result, Failure):
        return _refusal(result)
    return Response(sku_dict(result), status=201)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def low_stock(request: Request) -> Response:
    """The pairs running out, from the read-only VIEW. The threshold lives in the database."""
    return Response([low_stock_dict(r) for r in usecases.low_stock(_session(request))])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def movement_book(request: Request) -> Response:
    """The movement book: the last lines of each origin, duplicates KEPT because they are events."""
    return Response(
        [ledger_line_dict(line) for line in usecases.movement_book(_session(request))]
    )


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def warehouse_stats(request: Request) -> Response:
    """Every warehouse with its aggregates, in ONE statement."""
    rows = usecases.warehouse_stats(_session(request))
    return Response([warehouse_stats_dict(s) for s in rows])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def paginate_stock(request: Request) -> Response:
    """One page of stock together with what the pager needs. TWO statements, whatever the size."""
    page = usecases.paginate_stock(
        _session(request),
        warehouse_id=_optional_warehouse(request),
        page=_int(request, "page", 1),
        per_page=_int(request, "per_page", 20),
    )
    return Response(stock_page_dict(page))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def stock_report(request: Request) -> Response:
    """The whole inventory report: annotate, GROUP BY + HAVING, a window, a DISTINCT JOIN and a count."""
    report = usecases.stock_report(
        _session(request),
        minimum_moves=_int(request, "minimum_moves", 2),
        ranking_size=_int(request, "ranking_size", 50),
    )
    return Response(stock_report_dict(report))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def export_movements(request: Request) -> Response:
    """The stock movements as a STREAM, drained into the response.

    Drained HERE and not inside the use case, for the reason `apps/orders/api.py` sets out over its
    own export: the response is one document, and what streaming buys is that the RESULT SET is not.
    """
    movements = usecases.stream_movements(
        _session(request), warehouse_id=_optional_warehouse(request)
    )
    return Response([movement_dict(movement) for movement in movements])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def stock_of_warehouse(request: Request, warehouse_id: int) -> Response:
    """A warehouse's stock with its SKU loaded: one statement, no N+1."""
    result = usecases.stock_of_warehouse(_session(request), warehouse_id)
    if isinstance(result, Failure):
        return _refusal(result)
    return Response([stock_dict(row) for row in result])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def stock_with_movements(request: Request, warehouse_id: int) -> Response:
    """Stock with each row's movements: the to-many over a COMPOSITE foreign key."""
    result = usecases.stock_with_movements(_session(request), warehouse_id)
    if isinstance(result, Failure):
        return _refusal(result)
    return Response(
        [
            {**stock_dict(row), "movements": [movement_dict(m) for m in row.movements]}
            for row in result
        ]
    )


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def movements_of(request: Request, warehouse_id: int, sku_id: int) -> Response:
    """The movements of ONE stock row, addressed by both halves of its key."""
    result = usecases.movements_of(_session(request), warehouse_id, sku_id)
    if isinstance(result, Failure):
        return _refusal(result)
    return Response([movement_dict(m) for m in result])


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def receive(request: Request, warehouse_id: int, sku_id: int) -> Response:
    """Receive goods into a pair, creating the stock row if it was not there."""
    result = usecases.receive(
        _session(request),
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        units=wire.integer(wire.json_object(request).get("units")),
    )
    if isinstance(result, Failure):
        return _refusal(result)
    return Response(stock_dict(result))


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def ship(request: Request, warehouse_id: int, sku_id: int) -> Response:
    """Ship goods out. 409 if there are not that many: the rule refuses BEFORE writing."""
    result = usecases.ship(
        _session(request),
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        units=wire.integer(wire.json_object(request).get("units")),
    )
    if isinstance(result, Failure):
        return _refusal(result)
    return Response(stock_dict(result))


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PUT", "PATCH", "DELETE"])
def stock_pair(request: Request, warehouse_id: int, sku_id: int) -> Response:
    """The READ and the three writes over ONE pair, told apart by the METHOD rather than by four URLs.

    They are four different operations and the verb is what says which, which is also the only way
    Django can route them: a path maps to one view, so the dispatch happens here instead of in the
    urlconf. The other two demos get the same four verbs on the same path.

    GET fetches the pair with its warehouse and its SKU loaded, in one statement. It is here because
    it was NOT: this resource answered the three writes and no read at all, so a client could count,
    correct and delete a row it had no way of fetching — and the only route that would show it to
    them was an HTML page. A resource one surface can write and cannot read is not a resource.

    PUT is a physical count: an UPSERT over the composite key, meaning "this pair now holds N
    whether or not it existed". PATCH corrects BOTH levels of a pair that is already there, so a pair
    that vanished between the form being drawn and being submitted is a 404 rather than a silent
    insert. DELETE removes it, and refuses with 409 when its movements would be orphaned — the
    foreign key is RESTRICT, so a pair that has moved gets closed, not deleted.
    """
    session = _session(request)
    if request.method == "GET":
        found = usecases.get_stock(session, warehouse_id, sku_id)
        if isinstance(found, Failure):
            return _refusal(found)
        return Response(stock_with_relations_dict(found))

    body = wire.json_object(request)
    if request.method == "PATCH":
        corrected = usecases.update_stock(
            session,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            on_hand=wire.integer(body.get("on_hand")),
            reserved=wire.integer(body.get("reserved")),
        )
        if isinstance(corrected, Failure):
            return _refusal(corrected)
        return Response(stock_dict(corrected))
    if request.method == "DELETE":
        removed = usecases.remove_stock(
            session, warehouse_id=warehouse_id, sku_id=sku_id
        )
        if isinstance(removed, Failure):
            return _refusal(removed)
        return Response(status=204)
    result = usecases.count_stock(
        session,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        on_hand=wire.integer(body.get("on_hand")),
    )
    if isinstance(result, Failure):
        return _refusal(result)
    return Response({"warehouse_id": warehouse_id, "sku_id": sku_id})


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def reserve(request: Request, warehouse_id: int) -> Response:
    """Reserve units across the warehouse's whole stock in ONE statement."""
    result = usecases.reserve(
        _session(request),
        warehouse_id=warehouse_id,
        units=wire.integer(wire.json_object(request).get("units")),
    )
    if isinstance(result, Failure):
        return _refusal(result)
    return Response({"rows": result})
