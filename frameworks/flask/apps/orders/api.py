"""JSON API of the orders domain (orders, their lines, the stock they hold and the money): thin endpoints.

Every endpoint parses the request, calls the use case with flat parameters and translates the result
into JSON (data -> DTO, `Failure` -> `abort(status)`). Zero queries and zero `commit` here. The ORM
session is opened by the blog's `before_app_request` hook in `g.session`.

THE MIRROR OF THE PAGES, AND WHY THE URLS DO NOT MATCH THEM. `apps/orders/urls.py` serves the same
domain as HTML and its paths look nothing like these, which is structural rather than sloppy: a page
has to SHOW a form before it can accept one, and a browser `<form>` emits only GET and POST — so
deleting is `POST /orders/delete/<id>` there and `DELETE /api/orders/<id>` here. What has to match is
the OPERATION, and `shared/tests/test_the_pages_and_the_api_do_the_same_things.py` is what checks it.

`payment_declined` IS AN ANSWER, not a server error: 402 through the same `FAILURE_STATUS` table
every other refusal goes through. A declined card is not a bad request and not a conflict — the order
was fine and the money did not arrive.
"""

from __future__ import annotations

from flask import abort, g, jsonify, request
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from apps import wire
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

orders = Blueprint(
    # `-api` because the plain `orders` belongs to the PAGES in `urls.py`, the same split
    # `billing`/`billing-api` and `inventory`/`inventory-api` already make: two blueprints cannot
    # share one `url_for` name.
    "orders-api",
    __name__,
    url_prefix="/api/orders",
    description="Orders: their lines, the stock they hold and the money they settle",
)


def _int_arg(name: str, default: int) -> int:
    """A query-string integer, falling back rather than raising: the value comes from a URL."""
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


@orders.get("")
def list_orders() -> ResponseReturnValue:
    """Every order with its customer, warehouse and invoice loaded, optionally narrowed to a state."""
    rows = usecases.list_orders(g.session, state=parse_state(request.args.get("state")))
    return jsonify([order_with_parties_dict(order) for order in rows])


@orders.get("/page")
def paginate_orders() -> ResponseReturnValue:
    """One page of orders together with what the pager needs. TWO statements, whatever the history."""
    customer = request.args.get("customer_id")
    return jsonify(
        order_page_dict(
            usecases.paginate_orders(
                g.session,
                state=parse_state(request.args.get("state")),
                customer_id=int(customer) if customer and customer.isdigit() else None,
                page=_int_arg("page", 1),
                per_page=_int_arg("per_page", 20),
            )
        )
    )


@orders.get("/report")
def order_report() -> ResponseReturnValue:
    """The whole orders report: annotate, GROUP BY + HAVING, GROUP BY, a window and a UNION."""
    return jsonify(
        order_report_dict(
            usecases.order_report(
                g.session,
                minimum_orders=_int_arg("minimum_orders", 2),
                sequence_size=_int_arg("sequence_size", 20),
                highlight_size=_int_arg("highlight_size", 5),
            )
        )
    )


@orders.get("/states")
def orders_per_state() -> ResponseReturnValue:
    """How many orders and how much money sit in each state. One row per state, one statement."""
    return jsonify(
        [state_total_dict(row) for row in usecases.orders_per_state(g.session)]
    )


@orders.get("/customers")
def customer_orders() -> ResponseReturnValue:
    """Every customer with their order count and what they have spent, typed, in one statement."""
    return jsonify(
        [customer_orders_dict(row) for row in usecases.customer_orders(g.session)]
    )


@orders.get("/export")
def export_lines() -> ResponseReturnValue:
    """The order lines as a STREAM, drained into the response.

    Drained HERE and not inside the use case, which is the honest shape for a JSON endpoint: the
    response is one document, so it exists whole whatever the read did. What streaming buys is that
    the RESULT SET never does — the rows arrive in chunks instead of the driver materialising the lot.
    """
    lines = usecases.stream_order_lines(
        g.session, state=parse_state(request.args.get("state"))
    )
    return jsonify([order_line_with_sku_dict(line) for line in lines])


@orders.get("/customers/<int:customer_id>")
def orders_of_customer(customer_id: int) -> ResponseReturnValue:
    """A customer's orders with each order's lines loaded; 404 if the customer does not exist."""
    result = usecases.orders_of_customer(g.session, customer_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify([order_dict(order) for order in result])


@orders.get("/<int:order_id>")
def get_order(order_id: int) -> ResponseReturnValue:
    """One order with its three parties loaded; 404 if it does not exist."""
    result = usecases.get_order(g.session, order_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(order_with_parties_dict(result))


@orders.get("/<int:order_id>/lines")
def order_lines(order_id: int) -> ResponseReturnValue:
    """An order's lines with the SKU loaded; 404 if the order does not exist."""
    result = usecases.order_lines(g.session, order_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify([order_line_with_sku_dict(line) for line in result])


@orders.post("")
def place_order() -> ResponseReturnValue:
    """Places an order: validates, prices every line off its SKU and writes it all in one commit."""
    payload = wire.json_object(request)
    result = usecases.place_order(
        g.session,
        reference=wire.text(payload.get("reference")),
        customer_id=wire.integer(payload.get("customer_id")),
        warehouse_id=wire.integer(payload.get("warehouse_id")),
        lines=wire.integer_pairs(payload.get("lines")),
    )
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(order_dict(result)), 201


@orders.put("/<int:order_id>/lines")
def set_line(order_id: int) -> ResponseReturnValue:
    """States how many units of a SKU an order wants, adding the line if it was not there. UPSERT.

    `PUT` and not `POST`, and the verb is the operation: setting a quantity is idempotent and
    survives a retried request, while adding would quietly double what the customer asked for.
    """
    payload = wire.json_object(request)
    result = usecases.set_line(
        g.session,
        order_id=order_id,
        sku_id=wire.integer(payload.get("sku_id")),
        quantity=wire.integer(payload.get("quantity")),
    )
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(order_line_with_sku_dict(result))


@orders.delete("/<int:order_id>/lines/<int:sku_id>")
def remove_line(order_id: int, sku_id: int) -> ResponseReturnValue:
    """Removes one line and leaves the order's total derived. BOTH halves of the key are required."""
    result = usecases.remove_line(g.session, order_id=order_id, sku_id=sku_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return "", 204


@orders.post("/<int:order_id>/invoice")
def attach_invoice(order_id: int) -> ResponseReturnValue:
    """Bills an open order against an EXISTING invoice and moves it to `INVOICED`."""
    payload = wire.json_object(request)
    result = usecases.attach_invoice(
        g.session, order_id=order_id, invoice_id=wire.integer(payload.get("invoice_id"))
    )
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(order_dict(result))


@orders.delete("/<int:order_id>")
def remove_order(order_id: int) -> ResponseReturnValue:
    """Deletes an order; 409 if it has lines, which is the FK-restrict path made explainable."""
    result = usecases.remove_order(g.session, order_id=order_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return "", 204


@orders.post("/<int:order_id>/reserve")
def reserve(order_id: int) -> ResponseReturnValue:
    """Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK. All of them or none.

    A shortage on any line refuses the WHOLE order with a 409: a partial reservation is not a state
    this domain has, and units held for an order that will never ship are indistinguishable from
    units held for one that will.
    """
    result = usecases.reserve(g.session, order_id=order_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(order_dict(result))


@orders.post("/<int:order_id>/settle")
def settle(order_id: int) -> ResponseReturnValue:
    """Bills a RESERVED order, takes the money and ships it. A declined charge answers 402.

    The invoice is issued OUTSIDE the savepoint and survives a decline, because a customer who has
    been sent a bill has been sent a bill; the payment, the shipment and the final state are inside
    it, because those must not exist if the money did not arrive.
    """
    payload = wire.json_object(request)
    result = usecases.settle(
        g.session,
        order_id=order_id,
        subscription_id=wire.integer(payload.get("subscription_id")),
        method=wire.text(payload.get("method"), "card"),
    )
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(order_dict(result))


@orders.post("/<int:order_id>/cancel")
def cancel_order(order_id: int) -> ResponseReturnValue:
    """Cancels an open order, giving back whatever it was holding. 409 once it has been billed.

    The two open states cancel DIFFERENTLY: from `DRAFT` nothing was promised, from `RESERVED` the
    hold has to be released or the shelf stays full while the warehouse starts refusing orders it
    could fill.
    """
    result = usecases.cancel_order(g.session, order_id=order_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(order_dict(result))
