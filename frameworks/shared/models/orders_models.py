"""ORDERS domain: the joint. An `Order` binds a `User` to a `Warehouse`, to its `Sku`s and to an `Invoice`.

This is the ninth domain and the last one there will be. It is not here to add width — eight were
already plenty — but because the graph had a hole in the middle of it. `inventory` moved stock that
nobody had ordered and `billing` invoiced subscriptions that had bought nothing: the two domains
where money, concurrency and transactions actually live never touched each other, so the operations
worth demonstrating had to be INVENTED. With an order in between they appear on their own:

    place → reserve stock → issue the invoice → settle it

and so do the two failures that make the ORM's hard parts matter. Two customers ordering the last
unit is a row lock, and an invoice that must not survive a reservation that got rolled back is a
savepoint. Neither is staged; both are what the flow does when it goes wrong.

WHAT THE ORDER OWNS. The order names ONE warehouse, and that is a modelling decision rather than a
simplification. `Stock`'s identity is the pair `(warehouse, sku)`, so a reservation has to know which
warehouse it is taking units out of; with the warehouse only on the line, the same order could reduce
three warehouses at once and there would be nothing left to lock as a unit. The line names the SKU
and the order names where it ships from, which is also how a real order behaves.

THE COMPOSITE KEY, THE SECOND ONE IN THE REPO. `OrderLine` is identified by `(order_id, sku_id)`. A
SKU appears at most ONCE in an order: wanting more of it raises the quantity, it does not open a
second line. A surrogate id would allow two lines for the same SKU and then "how many units of this
SKU does this order want" — the exact question the reservation asks of the stock row — stops having
one answer, and the two lines get reserved twice or half. The pair being the key is what makes the
duplicate impossible instead of merely unlikely.

That it is the second one is worth saying: `Stock`'s pair carries a QUANTITY, and this one carries
MONEY, so the shape is demonstrably not a quirk of the inventory. It also gives the select-in its
second two-placeholder-per-parent foreign key, from a different direction.

THE LINK TO BILLING is `Order.invoice_id`, and it is NULLABLE on purpose: a draft has no invoice and
a cancelled order never will. Nullable means the relationship is emitted as a LEFT JOIN, so an order
without an invoice still shows up on the listing rather than disappearing from it — which is what an
INNER JOIN would do, quietly, to every order that has not been billed yet.

`unit_price` is COPIED onto the line rather than read through to `Sku.price`. Prices change; an
invoice issued in March has to keep adding up in June. The line is a record of what was agreed, not
a pointer to what the catalogue says today.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from snakeorm import (
    SnakeColumn,
    SnakeIndex,
    SnakeModel,
    SnakeResult,
    SnakeToMany,
    SnakeToOne,
    SnakeUtc,
    snake_auto,
    snake_check,
    snake_checks,
    snake_datetimetz,
    snake_decimal,
    snake_enum,
    snake_indexes,
    snake_int,
    snake_model,
    snake_result,
    snake_str,
    snake_to_many,
    snake_to_one,
)

from shared.models.accounts_models import User
from shared.models.inventory_models import Sku, Warehouse

if TYPE_CHECKING:
    # For the TYPE-CHECKER only. At runtime `Invoice` is NOT imported: billing imports accounts and
    # orders imports both, so a real import here would close a cycle the moment billing ever wanted
    # to name an order. The linker gets the class through the globals injection in
    # `models/__init__.py`, which is the one place that has seen every domain.
    from shared.models.billing_models import Invoice


class OrderState(StrEnum):
    """Where an order is in the flow. Every transition out of one of these is an operation.

    The five are not decoration: they are what the operations of phase 3 move between, and what a
    report groups by. `RESERVED` exists as its own state instead of a boolean on the order because
    the units are being HELD at that point — cancelling from there has to give them back, and
    cancelling from `DRAFT` has nothing to give back. A boolean cannot tell those two apart.
    """

    DRAFT = "draft"
    RESERVED = "reserved"
    INVOICED = "invoiced"
    SETTLED = "settled"
    CANCELLED = "cancelled"


@snake_model(table="orders")
class Order(SnakeModel):
    """What a customer wants, from one warehouse, at a total computed from its lines.

    `total` is DERIVED and stored. Deriving it on every read would be honest too, but the report
    sums it across thousands of rows and a stored column is what lets that be one `SUM` instead of a
    join and a group. The price of storing it is that every write touching a line has to leave it
    consistent, which is why no service writes a line without the use case retotalling the order.
    """

    SnakeComment = "Customer orders: the joint between stock and billing"

    id: SnakeColumn[int] = snake_auto()
    # What a human quotes on the phone, so it is unique and short. The index is what makes the
    # look-up by reference a seek rather than a scan of the whole order history.
    reference: SnakeColumn[str] = snake_str(max_length=24, unique=True)
    state: SnakeColumn[OrderState] = snake_enum(
        OrderState, default=OrderState.DRAFT, index=True
    )
    total: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)
    customer_id: SnakeColumn[int] = snake_int(index=True)
    customer: SnakeToOne[User] = snake_to_one(customer_id)
    # NO `index=True`: `ix_orders_warehouse_state` at the foot of this file already indexes
    # `(warehouse_id, state)`, and a B-tree serves any filter on a LEFTMOST PREFIX of its columns.
    # A second index on the same leading column costs a write per insert and buys nothing.
    warehouse_id: SnakeColumn[int] = snake_int()
    warehouse: SnakeToOne[Warehouse] = snake_to_one(warehouse_id)
    # NULLABLE, so the relationship is a LEFT JOIN: an unbilled order stays on the listing.
    invoice_id: SnakeColumn[int | None] = snake_int(index=True)
    invoice: SnakeToOne["Invoice | None"] = snake_to_one(invoice_id)
    # Spread by the seeder over the history, like every other date in the demos, so a report over
    # time has something to show. A server default would freeze every seeded order at boot time.
    placed_at: SnakeColumn[SnakeUtc] = snake_datetimetz()
    lines: SnakeToMany["OrderLine"] = snake_to_many("order")


@snake_model(table="order_lines")
class OrderLine(SnakeModel):
    """One SKU wanted by one order. COMPOSITE PK `(order_id, sku_id)`.

    The pair IS the identity: a second row for the same order and the same SKU cannot mean anything
    that raising the quantity does not already mean. `unit_price` is the price AT THE TIME, copied
    from the SKU, because an order has to keep adding up after the catalogue is repriced.
    """

    SnakeComment = "One SKU wanted by one order"

    order_id: SnakeColumn[int] = snake_int(primary_key=True)
    sku_id: SnakeColumn[int] = snake_int(primary_key=True)
    order: SnakeToOne[Order] = snake_to_one(order_id)
    sku: SnakeToOne[Sku] = snake_to_one(sku_id)
    quantity: SnakeColumn[int] = snake_int()
    unit_price: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)


@snake_result
class CustomerOrders(SnakeResult[User]):
    """Typed container for `session.annotate()`: a customer and what they have ordered.

    Both aggregates are ONE hop from the user (`User.orders`), which is the depth `annotate` covers.
    What a report also wants —units, which lives two hops away through the lines— is a `group_by`
    and comes back as tuples; the same split `BlogStats` already documents for traffic per blog.
    """

    customer: User
    order_count: int
    ordered_total: Decimal


# Outside the class body: inside it `quantity` is still the raw descriptor and does not know its own
# name yet. A line of zero units is not an empty line, it is a line that should have been deleted,
# and the engine is the only place that holds when two requests edit the same order.
snake_checks(
    OrderLine,
    snake_check(OrderLine.quantity > 0, name="ck_order_lines_quantity_positive"),
    snake_check(
        OrderLine.unit_price >= 0,
        name="ck_order_lines_unit_price_not_negative",
    ),
)

# The order book of one warehouse, which is what the operations read: everything still to be shipped
# from here. Ordering by state and then by placement is the listing's own order, so the index serves
# the filter and the sort at once.
snake_indexes(
    Order,
    SnakeIndex(Order.warehouse_id, Order.state, name="ix_orders_warehouse_state"),
)


# The domain's models, in local dependency order for the DDL.
ORDERS_MODELS = (Order, OrderLine)
