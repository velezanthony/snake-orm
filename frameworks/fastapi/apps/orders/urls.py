"""Router of the orders domain (orders, their lines, the stock they hold and the money): a thin JSON API.

Every endpoint parses the request (Pydantic), calls the use case with flat parameters and translates
the result into JSON (data -> DTO, `Failure` -> HTTPException). Zero queries, zero `commit` here.

THE THREE OPERATIONS AT THE BOTTOM are why this router exists and not just to round the domain count
up to nine. `/reserve` locks stock rows under a declared isolation level, `/settle` bills, charges
and ships inside a savepoint that can rewind without losing the invoice, and `/cancel` gives back
what a reservation was holding. They are the only endpoints in these demos that ask the ASYNCHRONOUS
session to do anything harder than read and write, and until this file existed nothing outside
`src/test` asked it at all.

`payment_declined` IS AN ANSWER, not an error page. It maps to 402 through the same
`FAILURE_STATUS` table every other refusal goes through, because a declined card is not a bad
request and not a conflict: the order was fine and the money did not arrive. That the endpoint can
return it at all is the point — the charge is a parameter of `settle`, so the failing path is
reachable without breaking the database on purpose.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from apps.deps import SessionDep, http_error
from apps.orders import usecases
from apps.orders.usecases import Failure
from shared.dto.orders_dto import (
    customer_orders_dict,
    order_dict,
    order_line_with_sku_dict,
    order_page_dict,
    order_report_dict,
    order_with_parties_dict,
    state_total_dict,
)
from shared.models import OrderState

router = APIRouter(prefix="/api/orders", tags=["orders"])


class OrderIn(BaseModel):
    """Body for placing an order: the reference, the two parties and the `(sku_id, quantity)` pairs.

    `lines` is a list of PAIRS rather than a list of objects because that is the shape the composite
    key has, and it is the only one that cannot express a duplicate ambiguously. The use case refuses
    a repeated SKU rather than merging: a form that says two different things about one SKU is not a
    request to guess.
    """

    reference: str
    customer_id: int
    warehouse_id: int
    lines: list[tuple[int, int]]


class LineIn(BaseModel):
    """Body for stating how many units of a SKU an order wants. It SETS, it does not add."""

    sku_id: int
    quantity: int


class InvoiceIn(BaseModel):
    """Body for billing an open order against an invoice that already exists."""

    invoice_id: int


class SettleIn(BaseModel):
    """Body for settling a reserved order: which subscription it bills to, and how it is paid."""

    subscription_id: int
    method: str = "card"


@router.get("")
async def list_orders(
    session: SessionDep, state: OrderState | None = None
) -> list[dict[str, object]]:
    """Every order with its customer, warehouse and invoice loaded, optionally narrowed to a state."""
    return [
        order_with_parties_dict(order)
        for order in await usecases.list_orders(session, state=state)
    ]


@router.get("/page")
async def paginate_orders(
    session: SessionDep,
    state: OrderState | None = None,
    customer_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict[str, object]:
    """One page of orders together with what the pager needs. TWO statements, whatever the history."""
    return order_page_dict(
        await usecases.paginate_orders(
            session,
            state=state,
            customer_id=customer_id,
            page=page,
            per_page=per_page,
        )
    )


@router.get("/report")
async def order_report(
    session: SessionDep,
    minimum_orders: int = 2,
    sequence_size: int = 20,
    highlight_size: int = 5,
) -> dict[str, object]:
    """The whole orders report: annotate, GROUP BY + HAVING, GROUP BY, a window and a UNION."""
    return order_report_dict(
        await usecases.order_report(
            session,
            minimum_orders=minimum_orders,
            sequence_size=sequence_size,
            highlight_size=highlight_size,
        )
    )


@router.get("/states")
async def orders_per_state(session: SessionDep) -> list[dict[str, object]]:
    """How many orders and how much money sit in each state. One row per state, one statement."""
    return [state_total_dict(row) for row in await usecases.orders_per_state(session)]


@router.get("/customers")
async def customer_orders(session: SessionDep) -> list[dict[str, object]]:
    """Every customer with their order count and what they have spent, typed, in one statement."""
    return [
        customer_orders_dict(row) for row in await usecases.customer_orders(session)
    ]


@router.get("/export")
async def export_lines(
    session: SessionDep, state: OrderState | None = None
) -> list[dict[str, object]]:
    """The order lines as a STREAM, drained into the response.

    The stream is what the use case hands back and it is drained HERE rather than inside it, which
    is the honest shape for a JSON endpoint: the response is one document, so it exists whole
    whatever the read did. What streaming buys is that the RESULT SET never does — the rows arrive
    in chunks from the server instead of the driver materialising the lot before this loop starts.
    """
    return [
        order_line_with_sku_dict(line)
        async for line in await usecases.stream_order_lines(session, state=state)
    ]


@router.get("/customers/{customer_id}")
async def orders_of_customer(
    customer_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """A customer's orders with each order's lines loaded; 404 if the customer does not exist."""
    result = await usecases.orders_of_customer(session, customer_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return [order_dict(order) for order in result]


@router.get("/{order_id}")
async def get_order(order_id: int, session: SessionDep) -> dict[str, object]:
    """One order with its three parties loaded; 404 if it does not exist."""
    result = await usecases.get_order(session, order_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return order_with_parties_dict(result)


@router.get("/{order_id}/lines")
async def order_lines(order_id: int, session: SessionDep) -> list[dict[str, object]]:
    """An order's lines with the SKU loaded; 404 if the order does not exist."""
    result = await usecases.order_lines(session, order_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return [order_line_with_sku_dict(line) for line in result]


@router.post("", status_code=201)
async def place_order(body: OrderIn, session: SessionDep) -> dict[str, object]:
    """Places an order: validates, prices every line off its SKU and writes it all in one commit."""
    result = await usecases.place_order(
        session,
        reference=body.reference,
        customer_id=body.customer_id,
        warehouse_id=body.warehouse_id,
        lines=body.lines,
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return order_dict(result)


@router.put("/{order_id}/lines")
async def set_line(
    order_id: int, body: LineIn, session: SessionDep
) -> dict[str, object]:
    """States how many units of a SKU an order wants, adding the line if it was not there. UPSERT.

    `PUT` and not `POST`, and the verb is the operation: setting a quantity is idempotent and
    survives a retried request, while adding would quietly double what the customer asked for.
    """
    result = await usecases.set_line(
        session, order_id=order_id, sku_id=body.sku_id, quantity=body.quantity
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return order_line_with_sku_dict(result)


@router.delete("/{order_id}/lines/{sku_id}", status_code=204)
async def remove_line(order_id: int, sku_id: int, session: SessionDep) -> None:
    """Removes one line and leaves the order's total derived. BOTH halves of the key are required."""
    result = await usecases.remove_line(session, order_id=order_id, sku_id=sku_id)
    if isinstance(result, Failure):
        raise http_error(result)


@router.post("/{order_id}/invoice")
async def attach_invoice(
    order_id: int, body: InvoiceIn, session: SessionDep
) -> dict[str, object]:
    """Bills an open order against an EXISTING invoice and moves it to `INVOICED`."""
    result = await usecases.attach_invoice(
        session, order_id=order_id, invoice_id=body.invoice_id
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return order_dict(result)


@router.delete("/{order_id}", status_code=204)
async def remove_order(order_id: int, session: SessionDep) -> None:
    """Deletes an order; 409 if it has lines, which is the FK-restrict path made explainable."""
    result = await usecases.remove_order(session, order_id=order_id)
    if isinstance(result, Failure):
        raise http_error(result)


@router.post("/{order_id}/reserve")
async def reserve(order_id: int, session: SessionDep) -> dict[str, object]:
    """Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK. All of them or none.

    A shortage on any line refuses the WHOLE order with a 409: a partial reservation is not a state
    this domain has, and units held for an order that will never ship are indistinguishable from
    units held for one that will.
    """
    result = await usecases.reserve(session, order_id=order_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return order_dict(result)


@router.post("/{order_id}/settle")
async def settle(
    order_id: int, body: SettleIn, session: SessionDep
) -> dict[str, object]:
    """Bills a RESERVED order, takes the money and ships it. A declined charge answers 402.

    The invoice is issued OUTSIDE the savepoint and survives a decline, because a customer who has
    been sent a bill has been sent a bill; the payment, the shipment and the final state are inside
    it, because those must not exist if the money did not arrive. The reservation is released on the
    way out, in the same transaction the savepoint rewound — which is what a savepoint buys over a
    rollback, and why this endpoint can answer 402 instead of exploding.
    """
    result = await usecases.settle(
        session,
        order_id=order_id,
        subscription_id=body.subscription_id,
        method=body.method,
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return order_dict(result)


@router.post("/{order_id}/cancel")
async def cancel_order(order_id: int, session: SessionDep) -> dict[str, object]:
    """Cancels an open order, giving back whatever it was holding. 409 once it has been billed.

    The two open states cancel DIFFERENTLY: from `DRAFT` nothing was promised, from `RESERVED` the
    hold has to be released or the shelf stays full while the warehouse starts refusing orders it
    could fill. Undoing money is a refund and undoing a shipment is a return, and this is neither.
    """
    result = await usecases.cancel_order(session, order_id=order_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return order_dict(result)
