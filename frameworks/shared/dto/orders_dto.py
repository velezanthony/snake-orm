"""DTOs for the orders domain. Flat and JSON-able.

Same bargain as the other DTO modules: a `Decimal` goes out as a STRING and not as a float, because
the total is exact in the database and in Python and `json.dumps` on a float is precisely where the
cent goes missing. An instant goes out in its textual ISO form, identical on the three engines.

A `state` goes out as its VALUE and not its name — `"reserved"`, not `"RESERVED"` — because the enum
is stored by value and a client that reads a listing and posts a filter back has to be able to send
what it was given.

THE RELATIONSHIPS ARE OPTIONAL AND THE DTO SAYS SO. An order carries a customer, a warehouse and an
invoice, and only the pages that asked for them have them loaded: the operations read the order bare
on purpose, since a write path wants the row and not the three rows it points at. So `order_dict`
serialises the ids, which are always there, and `order_with_parties_dict` is what a page that
included them calls. Reaching for `order.customer.username` in the plain one would raise
`SnakeRelationshipNotLoaded` — which is the ORM shouting rather than guessing, and exactly the error
this split exists to keep out of a response.
"""

from __future__ import annotations

from decimal import Decimal

from shared.models import CustomerOrders, Order, OrderLine, OrderState
from shared.usecases.orders_usecases import OrderPage, OrderReport


def order_dict(order: Order) -> dict[str, object]:
    """An order as a dict, with its three parties as ids. Nothing here needs a relationship loaded."""
    return {
        "id": order.id,
        "reference": order.reference,
        "state": order.state.value,
        "total": str(order.total),
        "customer_id": order.customer_id,
        "warehouse_id": order.warehouse_id,
        "invoice_id": order.invoice_id,
        "placed_at": order.placed_at.isoformat(),
    }


def order_with_parties_dict(order: Order) -> dict[str, object]:
    """An order plus the names of its customer, warehouse and invoice. Needs `with_parties` loaded.

    The invoice is nullable in the schema and therefore nullable here: an order that has not been
    billed yet has no invoice, which is a state and not a missing value.
    """
    return {
        **order_dict(order),
        "customer": order.customer.username,
        "warehouse": order.warehouse.code,
        "invoice_amount_cents": (
            order.invoice.amount_cents if order.invoice is not None else None
        ),
    }


def order_line_dict(line: OrderLine) -> dict[str, object]:
    """One line as a dict, with the SKU as an id. Its key is the PAIR, and both halves travel."""
    return {
        "order_id": line.order_id,
        "sku_id": line.sku_id,
        "quantity": line.quantity,
        "unit_price": str(line.unit_price),
    }


def order_line_with_sku_dict(line: OrderLine) -> dict[str, object]:
    """One line plus its SKU's name. Needs `include(OrderLine.sku)`."""
    return {**order_line_dict(line), "sku": line.sku.name}


def order_page_dict(page: OrderPage) -> dict[str, object]:
    """A page of orders WITH what the pager needs, which travels with the rows rather than beside them.

    The four go out together because they are ONE answer: a client that asks for the total separately
    is the client that filters the two questions differently, and then draws a pager saying 47 over a
    listing showing a different 47.
    """
    return {
        "rows": [order_with_parties_dict(order) for order in page.rows],
        "total": page.total,
        "page": page.page,
        "pages": page.pages,
    }


def customer_orders_dict(row: CustomerOrders) -> dict[str, object]:
    """A customer with how many orders they placed and what they spent, from ONE annotated read.

    The row is a `SnakeResult[User]`, so the customer arrives as a WHOLE `User` under `.customer`
    rather than as flattened columns — which is the shape `annotate` gives and the reason this
    serialiser reaches one level in.
    """
    return {
        "id": row.customer.id,
        "username": row.customer.username,
        "order_count": row.order_count,
        "ordered_total": str(row.ordered_total),
    }


def state_total_dict(row: tuple[OrderState, int, Decimal]) -> dict[str, object]:
    """One `GROUP BY state` row: the state, how many orders sit in it and how much money."""
    state, orders, total = row
    return {"state": state.value, "orders": orders, "total": str(total)}


def repeat_customer_dict(row: tuple[str, int, Decimal]) -> dict[str, object]:
    """One `GROUP BY ... HAVING COUNT(*) >= n` row: a customer who came back."""
    username, placed, spent = row
    return {"username": username, "orders": placed, "spent": str(spent)}


def order_report_dict(report: OrderReport) -> dict[str, object]:
    """The whole orders report as one payload: every figure of `OrderReport`, one key each.

    IT SAID FIVE, AND `baskets` WAS THE ONE IT DROPPED. `OrderReport` has six fields and this
    function shipped five, so `/api/orders/report` never carried a table that BOTH SSR demos
    paint. Nothing could see it: the page and the endpoint reach the same use case, the routes
    exist in the three demos, and the statement budget still counted the query — the figure was
    fetched from the engine and thrown away on the way out. `shared/dto/` is the only layer where
    that can happen, and `test_a_report_payload_carries_every_figure` is the net that now reads
    this dict against `dataclasses.fields()` instead of trusting a count in a docstring.

    `highlights` carries BARE orders and the shape says so by using `order_dict` rather than its
    sibling: a `UNION` loads no relationships at all, so those rows know their own columns and
    nothing else. Serialising them with the parties would raise while rendering the response, which
    is the worst place to find out.
    """
    return {
        "customers": [customer_orders_dict(row) for row in report.customers],
        "repeat_customers": [
            repeat_customer_dict(row) for row in report.repeat_customers
        ],
        "states": [state_total_dict(row) for row in report.states],
        "sequence": [
            {
                "reference": reference,
                "customer": username,
                "placed_at": placed_at.isoformat(),
                "position": position,
            }
            for reference, username, placed_at, position in report.sequence
        ],
        "highlights": [order_dict(order) for order in report.highlights],
        "baskets": [
            {"reference": reference, "lines": lines, "skus": skus}
            for reference, lines, skus in report.baskets
        ],
    }
