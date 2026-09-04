"""Thin JSON API for the orders domain (orders, lines, the stock they hold and the money): DRF over `shared`.

Thin views (`@api_view`): they parse the request, call the use case with flat parameters and
serialize with the shared DTOs (data) or map the `Failure` to its status (error). Zero queries, zero
`commit`. The SnakeORM session is hung on `request.snake_session` by `SnakeSessionMiddleware`.

ONE URL, ONE VIEW, which is Django's routing and the reason three views below dispatch on the
method. `apps/billing/api.py` already makes the same move for its `subscriptions/{id}/invoices`, and
it is the honest translation of a REST surface into a urlconf rather than a shape imposed on it: the
collection route answers GET and POST, the item route GET and DELETE, and the lines route GET and
PUT. What must not happen is one URL per verb, because then `/api/orders` stops being the resource.

THE MIRROR OF THE PAGES, AND WHY THE URLS DO NOT MATCH THEM. `web_urls.py` serves this same domain
as HTML and its paths look nothing like these: a page has to SHOW a form before it can accept one,
and a browser `<form>` emits only GET and POST, so deleting is `POST /orders/delete/<id>` there and
`DELETE /api/orders/<id>` here. What has to match is the OPERATION, and
`shared/tests/test_the_pages_and_the_api_do_the_same_things.py` is what checks it.

`payment_declined` IS AN ANSWER: 402 through the same `FAILURE_STATUS` table every other refusal
goes through. A declined card is not a bad request and not a conflict — the order was fine and the
money did not arrive.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


from apps import wire
from apps.session import snake_session
from apps.orders import usecases
from shared.dto.orders_dto import (
    customer_orders_dict,
    order_dict,
    order_line_with_sku_dict,
    order_page_dict,
    order_report_dict,
    order_with_parties_dict,
    state_total_dict,
)
from shared.usecases.result import FAILURE_STATUS
from shared.viewmodels.orders_viewmodels import parse_state


_session = snake_session


def _int(request: Request, name: str, default: int) -> int:
    """A query-string integer, falling back rather than raising: the value comes from a URL."""
    try:
        return int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        return default


def _refusal(failure: usecases.Failure) -> Response:
    """The refusal as a response: its reason, with the status that reason maps to.

    It takes the `Failure` and not the result, which is the whole difference. Taking the result meant
    answering `Response | None`, so the call site read `return _refused(x) or Response(order_dict(x))`
    — one line, and unTYPEABLE: the `or` proves nothing about `x`, which stays `Order | Failure` into
    a function that wants an `Order`. Those calls type-checked here only because nothing was checking
    this app at all; the same idiom in `inventory/api.py`, which mypy HAD seen once, carried nine
    `# type: ignore` for it. An `isinstance` at the call site costs two lines and narrows for real.
    """
    return Response({"detail": failure.reason}, status=FAILURE_STATUS[failure.reason])


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "POST"])
def orders(request: Request) -> Response:
    """GET: every order with its three parties. POST: places one, priced off its SKUs, in one commit."""
    session = _session(request)
    if request.method == "GET":
        rows = usecases.list_orders(
            session, state=parse_state(request.query_params.get("state"))
        )
        return Response([order_with_parties_dict(order) for order in rows])

    body = wire.json_object(request)
    placed = usecases.place_order(
        session,
        reference=wire.text(body.get("reference")),
        customer_id=wire.integer(body.get("customer_id")),
        warehouse_id=wire.integer(body.get("warehouse_id")),
        lines=wire.integer_pairs(body.get("lines")),
    )
    if isinstance(placed, usecases.Failure):
        return _refusal(placed)
    return Response(order_dict(placed), status=201)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def paginate_orders(request: Request) -> Response:
    """One page of orders together with what the pager needs. TWO statements, whatever the history."""
    customer = request.query_params.get("customer_id")
    page = usecases.paginate_orders(
        _session(request),
        state=parse_state(request.query_params.get("state")),
        customer_id=int(customer) if customer and customer.isdigit() else None,
        page=_int(request, "page", 1),
        per_page=_int(request, "per_page", 20),
    )
    return Response(order_page_dict(page))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def order_report(request: Request) -> Response:
    """The whole orders report: annotate, GROUP BY + HAVING, GROUP BY, a window and a UNION."""
    report = usecases.order_report(
        _session(request),
        minimum_orders=_int(request, "minimum_orders", 2),
        sequence_size=_int(request, "sequence_size", 20),
        highlight_size=_int(request, "highlight_size", 5),
    )
    return Response(order_report_dict(report))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def orders_per_state(request: Request) -> Response:
    """How many orders and how much money sit in each state. One row per state, one statement."""
    rows = usecases.orders_per_state(_session(request))
    return Response([state_total_dict(row) for row in rows])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def customer_orders(request: Request) -> Response:
    """Every customer with their order count and what they have spent, typed, in one statement."""
    rows = usecases.customer_orders(_session(request))
    return Response([customer_orders_dict(row) for row in rows])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def export_lines(request: Request) -> Response:
    """The order lines as a STREAM, drained into the response.

    Drained HERE and not inside the use case: a JSON response is one document, so it exists whole
    whatever the read did. What streaming buys is that the RESULT SET never does.
    """
    lines = usecases.stream_order_lines(
        _session(request), state=parse_state(request.query_params.get("state"))
    )
    return Response([order_line_with_sku_dict(line) for line in lines])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def orders_of_customer(request: Request, customer_id: int) -> Response:
    """A customer's orders with each order's lines loaded; 404 if the customer does not exist."""
    result = usecases.orders_of_customer(_session(request), customer_id)
    if isinstance(result, usecases.Failure):
        return _refusal(result)
    return Response([order_dict(order) for order in result])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET", "DELETE"])
def order(request: Request, order_id: int) -> Response:
    """GET: one order with its three parties. DELETE: removes it, 409 if it still has lines."""
    session = _session(request)
    if request.method == "GET":
        found = usecases.get_order(session, order_id)
        if isinstance(found, usecases.Failure):
            return _refusal(found)
        return Response(order_with_parties_dict(found))

    removed = usecases.remove_order(session, order_id=order_id)
    if isinstance(removed, usecases.Failure):
        return _refusal(removed)
    return Response(status=204)


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PUT"])
def order_lines(request: Request, order_id: int) -> Response:
    """GET: the lines with their SKU. PUT: states how many units of a SKU the order wants. UPSERT.

    `PUT` and not `POST`, and the verb is the operation: setting a quantity is idempotent and
    survives a retried request, while adding would quietly double what the customer asked for.
    """
    session = _session(request)
    if request.method == "GET":
        lines = usecases.order_lines(session, order_id)
        if isinstance(lines, usecases.Failure):
            return _refusal(lines)
        return Response([order_line_with_sku_dict(line) for line in lines])

    body = wire.json_object(request)
    line = usecases.set_line(
        session,
        order_id=order_id,
        sku_id=wire.integer(body.get("sku_id")),
        quantity=wire.integer(body.get("quantity")),
    )
    if isinstance(line, usecases.Failure):
        return _refusal(line)
    return Response(order_line_with_sku_dict(line))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["DELETE"])
def remove_line(request: Request, order_id: int, sku_id: int) -> Response:
    """Removes one line and leaves the order's total derived. BOTH halves of the key are required."""
    result = usecases.remove_line(_session(request), order_id=order_id, sku_id=sku_id)
    if isinstance(result, usecases.Failure):
        return _refusal(result)
    return Response(status=204)


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def attach_invoice(request: Request, order_id: int) -> Response:
    """Bills an open order against an EXISTING invoice and moves it to `INVOICED`."""
    result = usecases.attach_invoice(
        _session(request),
        order_id=order_id,
        invoice_id=wire.integer(wire.json_object(request).get("invoice_id")),
    )
    if isinstance(result, usecases.Failure):
        return _refusal(result)
    return Response(order_dict(result))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def reserve(request: Request, order_id: int) -> Response:
    """Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK. All of them or none.

    A shortage on any line refuses the WHOLE order with a 409: a partial reservation is not a state
    this domain has, and units held for an order that will never ship are indistinguishable from
    units held for one that will.
    """
    result = usecases.reserve(_session(request), order_id=order_id)
    if isinstance(result, usecases.Failure):
        return _refusal(result)
    return Response(order_dict(result))


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def settle(request: Request, order_id: int) -> Response:
    """Bills a RESERVED order, takes the money and ships it. A declined charge answers 402.

    The invoice is issued OUTSIDE the savepoint and survives a decline, because a customer who has
    been sent a bill has been sent a bill; the payment, the shipment and the final state are inside
    it, because those must not exist if the money did not arrive.
    """
    body = wire.json_object(request)
    result = usecases.settle(
        _session(request),
        order_id=order_id,
        subscription_id=wire.integer(body.get("subscription_id")),
        method=wire.text(body.get("method"), "card"),
    )
    if isinstance(result, usecases.Failure):
        return _refusal(result)
    return Response(order_dict(result))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def cancel_order(request: Request, order_id: int) -> Response:
    """Cancels an open order, giving back whatever it was holding. 409 once it has been billed.

    The two open states cancel DIFFERENTLY: from `DRAFT` nothing was promised, from `RESERVED` the
    hold has to be released or the shelf stays full while the warehouse starts refusing orders it
    could fill.
    """
    result = usecases.cancel_order(_session(request), order_id=order_id)
    if isinstance(result, usecases.Failure):
        return _refusal(result)
    return Response(order_dict(result))
