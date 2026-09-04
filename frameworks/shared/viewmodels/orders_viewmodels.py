"""orders view models: the pages of the domain that can fail halfway through.

No count in that line, and deliberately: the pilot's twin carried "the five pages" long after it had
eight, and a number in prose ages exactly like a number in a table with nothing to catch either.

`inventory_viewmodels` is the pilot and its four rules hold here unchanged — go through the use
cases, return a `TypedDict`, hand back a `Failure` untouched, emit nothing but primitives. What this
module adds is the two things `orders` has that no other domain does: a page that OFFERS operations,
and rules about when each operation may be offered at all.

**THE RULE THAT IS NOT STYLE. A view model must never run on the way to an operation.**

`reserve`, `settle` and `cancel_order` open with `session.set_isolation(READ COMMITTED)`, and
`SET TRANSACTION ISOLATION LEVEL` is only valid before the transaction has read anything. A view
model is a READ, and a read starts the transaction. So a handler that draws the page and then
performs the operation on the SAME session has already spent the one moment the operation needed.

WHAT THAT COSTS IS WORSE THAN AN ERROR, and it was measured on a real server rather than assumed.
Postgres only refuses the statement when it would CHANGE the level: asking for the level the
transaction already has is accepted and does nothing. The demos run on a stock Postgres, whose
default IS `READ COMMITTED`, so the broken order of calls raises NOTHING and the operation runs at
the right level by luck. What has quietly happened is that the operation stopped DECLARING its
isolation and started INHERITING it — and `default_transaction_isolation` is a server-wide setting,
while MySQL, which these demos also run on, defaults to `REPEATABLE READ`. That is precisely the
level `test_orders_concurrency.py` measures as fatal: the second customer does not wait and refuse,
it dies with `could not serialize access due to concurrent update`.

So the failure is silent on the machine where it is written and loud on the machine where it is
deployed, which is the worst shape a bug can have. The line that will one day be written here is
"load the order so the flash message can say its reference", and this paragraph is for whoever is
about to write it. The read that RENDERS a page and the call that PERFORMS an operation are two
requests, with a session each. If they ever have to share one, the read's transaction has to be
closed —`session.rollback()`— before the operation is invoked.

SQLite hides even the loud half: it answers `Nope` to row locking, so `_open_stock_transaction` skips
the `SET` entirely. `test_orders_viewmodels.py` pins both halves on a real Postgres — the silence and
the error — for exactly that reason.

**WHERE THE `can_*` BOOLEANS COME FROM, and why they are not in the template.** `reserve` wants a
`DRAFT`, `settle` wants a `RESERVED`, `cancel_order` wants either. A template that spells that out as
`state == "draft" or state == "reserved"` is a copy of the domain's rules living in the one layer
nothing tests — and there are two SSR demos, so it is two copies that drift apart. They are computed
here, and the tests check them by running the operations rather than against a table of expectations.

**One key is missing from the listing on purpose: `line_count`.** No use case answers "how many lines
does each of these orders have" in bulk, and this ORM refuses to lazy-load a relation
(`SnakeRelationshipNotLoaded`) rather than quietly firing a query per row — so a count on the listing
would be an N+1 the budget test is there to catch. The pages that HAVE the lines carry the number
(`order_delete_confirm`) or the lines themselves (`order_detail`, `order_operation`), and the listing
does without. Closing that gap means a bulk count in `orders_selectors`, not a loop here.
"""

from __future__ import annotations

from decimal import Decimal
from typing_extensions import TypedDict

from snakeorm import SnakeSession

from shared.models import (
    CustomerOrders,
    Invoice,
    Order,
    OrderLine,
    OrderState,
    Sku,
    Stock,
    Subscription,
    Warehouse,
)
from shared.usecases import billing_usecases, inventory_usecases
from shared.usecases import orders_usecases as usecases
from shared.usecases.result import Failure

# The option shapes are IMPORTED and not redeclared, and mypy is what makes that worth doing: a
# warehouse in a `<select>` is the same thing on an order form as on a stock form, and the day
# `inventory_viewmodels` adds a key to either, the builders below stop type-checking until they
# agree. Two local copies would keep passing, and the two demos' pickers would drift.
from shared.viewmodels import billing_viewmodels
from shared.viewmodels.inventory_viewmodels import CsvExport, SkuOption, WarehouseOption

# What a person reads instead of the enum's value. Written out rather than derived from the member
# name, because a label has to be free to stop matching the value it names — and because a table
# that can fall behind the enum is a table a test can catch falling behind it.
_STATE_LABELS: dict[OrderState, str] = {
    OrderState.DRAFT: "Draft",
    OrderState.RESERVED: "Reserved",
    OrderState.INVOICED: "Invoiced",
    OrderState.SETTLED: "Settled",
    OrderState.CANCELLED: "Cancelled",
}

# The state rules of the three operations, mirrored from `orders_usecases`. They are sets and not
# comparisons for the reason the use case gives for its own: the day `RESERVED` stops being
# cancellable it has to stop in one place, and a test runs the operations to prove these agree.
_RESERVABLE = frozenset({OrderState.DRAFT})
_SETTLEABLE = frozenset({OrderState.RESERVED})
_CANCELLABLE = frozenset({OrderState.DRAFT, OrderState.RESERVED})
# `attach_invoice` bills an order against an invoice that ALREADY exists, so it takes any OPEN
# order — the same set the use case checks. It is the plain half of the joint with `billing`;
# `settle` is the half that issues the invoice, takes the money and needs a savepoint.
_ATTACHABLE = frozenset({OrderState.DRAFT, OrderState.RESERVED})


class StateOption(TypedDict):
    """One state as a `<select>` option: the value a form posts back and the words it shows."""

    value: str
    label: str


class CustomerOption(TypedDict):
    """A customer as a `<select>` option, with how many orders they already have.

    The count rides along because it costs nothing: `customer_orders` answers it as a correlated
    aggregate inside the one statement that lists the customers, so a picker that shows it and a
    picker that does not are the same query.
    """

    id: int
    username: str
    order_count: int


class SubscriptionOption(TypedDict):
    """A subscription as a `<select>` option: what `settle` bills the order against.

    It exists because `settle` needs a `subscription_id` and refuses one belonging to anybody but the
    order's customer. A page that offered a free-text field, or every subscription in the database,
    would be handing the user a 409 to click on.
    """

    id: int
    plan: str
    price: str
    active: bool


class InvoiceInfo(TypedDict):
    """The invoice an order was billed against, flattened. `amount` is money, not cents.

    `billing` stores money as an integer count of cents so it is exact on every engine; a page needs
    `10.00`. The conversion is one division and therefore exactly the kind of thing two templates
    would write two ways — one of them with a float.
    """

    id: int
    amount: str
    paid: bool
    issued_at: str


class OrderRow(TypedDict):
    """One order as every page carries it, with the three to-one hops ALREADY made.

    `customer` and `warehouse` are the flattened relations — reading them off the model in a template
    is a relation load inside the renderer, which is what this whole layer exists to stop. The two
    ids travel alongside their names because a form has to preselect and a link has to be built.

    `has_invoice` is a boolean rather than a nullable id, and that is deliberate: a listing wants to
    know THAT an order is billed, and an `invoice_id` of `None` printed into a table cell reads as
    the word "None". The invoice itself is a shape on the detail page, where there is something to
    branch on.

    THE THREE BOOLEANS ARE THE STATE RULES, and only those. It is all a listing can know — it has not
    read the stock and it has not read the customer's subscriptions. `order_operation` computes a
    narrower `can_settle` from what it HAS read, and says so where it does it.
    """

    id: int
    reference: str
    state: str
    state_label: str
    customer: str
    customer_id: int
    warehouse: str
    warehouse_id: int
    total: str
    placed_at: str
    has_invoice: bool
    can_reserve: bool
    can_settle: bool
    can_cancel: bool


class OrderLineRow(TypedDict):
    """One line of an order: the SKU named, the money formatted, the multiplication already done.

    `line_total` is `quantity * unit_price`, and it is here for the same reason the pilot's
    `available` is: one multiplication, two templates, two ways of rounding it.
    """

    sku_id: int
    sku_name: str
    quantity: int
    unit_price: str
    line_total: str


class OperationLineRow(OrderLineRow):
    """A line with what the warehouse actually holds for it, which is what the operation decides on.

    `available` is `on_hand - held` and not `on_hand`: units already promised to another order are
    still on the shelf, and the whole reservation race lives in that gap.

    `is_short` means "a reservation of this line would be refused if it ran right now". RIGHT NOW is
    the load-bearing part — this read is taken outside the lock, and `reserve` reads the rows again
    under `for_update` before it decides. So it is a warning, never a refusal. On an order that has
    already been reserved it reads oddly true, because the units this order is holding are counted in
    `held`; that is the honest number, and the page only warns about it where a reservation is on
    offer.
    """

    on_hand: int
    held: int
    available: int
    is_short: bool


class OrderListPage(TypedDict):
    """The listing plus its pager and its filter, which is everything the page needs to redraw itself.

    `state` comes back as the selected value so the template can mark its option, and as `""` rather
    than `None` when nothing is selected. `prev_page`/`next_page` come back already clamped so the
    template never does arithmetic on a page number.
    """

    rows: list[OrderRow]
    states: list[StateOption]
    state: str
    page: int
    pages: int
    total: int
    has_prev: bool
    has_next: bool
    prev_page: int
    next_page: int


class OrderDetailPage(TypedDict):
    """One order in full: the row, its lines, and the invoice if it has reached one.

    `lines_total` is the sum of the lines, next to `order["total"]`, which is stored. They should
    always agree — every write that touches a line retotals the order — and showing both is how a
    reader of these demos sees that a derived-and-stored column is a claim somebody has to keep true.
    """

    order: OrderRow
    lines: list[OrderLineRow]
    lines_total: str
    invoice: InvoiceInfo | None


class OrderFormPage(TypedDict):
    """What `create` and `update` both need, which is why it is ONE shape and one function.

    Three option lists because an order names three things: who it is for, where it ships from, and
    what is on it. `is_update` is the single difference between the two pages, said out loud.
    """

    customers: list[CustomerOption]
    warehouses: list[WarehouseOption]
    skus: list[SkuOption]
    order: OrderRow | None
    lines: list[OrderLineRow]
    is_update: bool


class OrderDeletePage(TypedDict):
    """The confirmation, and what a delete would take with it.

    The foreign key from the lines is RESTRICT, so an order with lines CANNOT be deleted and a
    confirmation that does not say so is a button that fails after being pressed. `can_delete` is
    that rule, and `blocked` is the sentence next to it.

    The lines are LISTED and not merely counted, which is the opposite of what the pilot's
    confirmation does with its movements — deliberately. An order has a handful of lines and knowing
    which SKUs go with it is the answer somebody wants; a stock row has a year of movements and
    naming them is a page nobody reads.
    """

    order: OrderRow
    lines: list[OrderLineRow]
    line_count: int
    can_delete: bool
    blocked: str


class OrderOperationPage(TypedDict):
    """The page the row lock, the isolation level and the savepoint are reached from.

    THE THREE BOOLEANS AT THIS LEVEL ARE THE ONES A BUTTON READS. They are the state rules narrowed
    by what this page has read and the listing has not: `can_settle` is additionally false when the
    customer has no subscription, because `settle` issues the invoice against one and would answer
    `not_found` after the click. The three inside `order` stay the pure state rules, which is what a
    listing can honestly claim.

    Each `*_blocked` is empty exactly when its boolean is true. A reason next to an enabled button
    explains something that is not happening; an empty reason next to a disabled one is a dead
    control. Both look fine until somebody reads the page.

    `reserve_warning` is not a refusal and must not be rendered as one — see `OperationLineRow`.

    NOTHING HERE PERFORMS ANYTHING. Building this page opens a transaction, and the three operations
    have to be handed a session that has none. See the module docstring.
    """

    order: OrderRow
    lines: list[OperationLineRow]
    subscriptions: list[SubscriptionOption]
    invoices: list[InvoiceInfo]
    can_reserve: bool
    can_settle: bool
    can_cancel: bool
    can_attach: bool
    reserve_blocked: str
    settle_blocked: str
    cancel_blocked: str
    attach_blocked: str
    reserve_warning: str


def state_label(state: OrderState) -> str:
    """What a person reads for a state. `KeyError` if a state has no label, on purpose.

    A sixth state added to the enum without a label has to fail loudly rather than print an empty
    cell, which is the same bargain `nav.section` makes for the same reason.
    """
    return _STATE_LABELS[state]


def parse_state(value: str | None) -> OrderState | None:
    """Turns a query-string value into a state filter: `None` for absent, empty or unrecognised.

    It lives here so the two demos do not each write a `try/except ValueError` around
    `OrderState(...)`, and it falls back to NO filter rather than to an empty listing. That is not
    the same choice the pilot makes for an unknown warehouse id, and the difference is real: an
    unknown id is still a filter the engine can run and correctly matches nothing, while an unknown
    state cannot be turned into a filter at all — the enum refuses to build it. So the alternatives
    here are "show everything" or "raise a `ValueError` at a hand-edited URL", and a typo in a query
    string is not a 500.
    """
    if not value:
        return None
    try:
        return OrderState(value)
    except ValueError:
        return None


def _money(amount: Decimal) -> str:
    """Money as text with its two decimals, because a template cannot round.

    The DTOs next door emit `str(...)` instead, and the difference is deliberate: JSON has to be
    exact because a machine reads it, and a page has to be legible because a person does.
    """
    return f"{amount:.2f}"


def _money_from_cents(cents: int) -> str:
    """`billing`'s integer cents as money, DELEGATED to the domain that stores them that way.

    The two domains disagree about how money is stored —`NUMERIC(12,2)` on an order, an integer count
    of cents on an invoice— and `orders_usecases._in_cents` is the same seam from the other side.
    This side used to do the conversion itself; it now calls `billing_viewmodels.money_from_cents`,
    because two formatters are two rounding rules waiting to disagree on the one kind of value where
    a disagreement shows up on somebody's bank statement.

    The wrapper stays rather than the callers being rewritten, so the name every function in this
    module reaches for is still the one next to `_money`.
    """
    return billing_viewmodels.money_from_cents(cents)


def _state_options() -> list[StateOption]:
    """Every state as a filter option, in the enum's own order. NO query: it is a Python constant.

    Which is why this listing costs one statement less than the pilot's: `inventory` filters by a
    table of warehouses and has to read it, and this one filters by a value the code already knows.
    """
    return [{"value": state.value, "label": state_label(state)} for state in OrderState]


def _order_row(order: Order) -> OrderRow:
    """An order flattened, doing the two to-one hops the template must not do.

    It REQUIRES the order to arrive with `customer` and `warehouse` loaded, which every use case that
    feeds it does with a single `include`. Reading them off a bare row would work and would cost two
    queries per line — the exact N+1 this layer was put in front of, just moved one file over.

    `invoice_id` and not `invoice` for `has_invoice`: the id is a column and is always there, so the
    boolean costs nothing and does not add a third relation to the list of things a caller has to
    have included.
    """
    return {
        "id": order.id,
        "reference": order.reference,
        "state": order.state.value,
        "state_label": state_label(order.state),
        "customer": order.customer.username,
        "customer_id": order.customer_id,
        "warehouse": order.warehouse.code,
        "warehouse_id": order.warehouse_id,
        "total": _money(order.total),
        "placed_at": order.placed_at.isoformat(),
        "has_invoice": order.invoice_id is not None,
        "can_reserve": order.state in _RESERVABLE,
        "can_settle": order.state in _SETTLEABLE,
        "can_cancel": order.state in _CANCELLABLE,
    }


def _line_row(line: OrderLine) -> OrderLineRow:
    """A line flattened: the SKU named, the money formatted, the multiplication already done.

    It REQUIRES `sku` to be loaded, which `order_lines` does with a single `include`.
    """
    return {
        "sku_id": line.sku_id,
        "sku_name": line.sku.name,
        "quantity": line.quantity,
        "unit_price": _money(line.unit_price),
        "line_total": _money(line.unit_price * line.quantity),
    }


def _operation_line_row(line: OrderLine, stock: Stock | None) -> OperationLineRow:
    """A line next to what the warehouse holds for it. A missing pair holds ZERO, not nothing.

    That is `reserve`'s own reading: a pair the warehouse has never held is a shortage like any
    other, not a `not_found`. The order exists and the SKU exists; what was asked is whether there
    are enough, and the answer is no.
    """
    on_hand = stock.on_hand if stock is not None else 0
    held = stock.reserved if stock is not None else 0
    available = on_hand - held
    row = _line_row(line)
    return {
        **row,
        "on_hand": on_hand,
        "held": held,
        "available": available,
        "is_short": available < line.quantity,
    }


def _customer_option(row: CustomerOrders) -> CustomerOption:
    """A customer flattened into an option, with the order count that came free with the statement."""
    return {
        "id": row.customer.id,
        "username": row.customer.username,
        "order_count": row.order_count,
    }


def _warehouse_option(warehouse: Warehouse) -> WarehouseOption:
    """A warehouse flattened into the option shape `inventory_viewmodels` declares."""
    return {"id": warehouse.id, "code": warehouse.code, "name": warehouse.name}


def _sku_option(sku: Sku) -> SkuOption:
    """A SKU flattened into the option shape `inventory_viewmodels` declares, price included."""
    return {
        "id": sku.id,
        "name": sku.name,
        "kind": sku.kind.value,
        "price": _money(sku.price),
    }


def _subscription_option(subscription: Subscription) -> SubscriptionOption:
    """A subscription flattened into an option, with the plan's name and price already formatted.

    It REQUIRES `plan` to be loaded, which `subscriptions_of_user` does with a single `include`.
    """
    return {
        "id": subscription.id,
        "plan": subscription.plan.name,
        "price": _money_from_cents(subscription.plan.price_cents),
        "active": subscription.active,
    }


def _invoice_info(invoice: Invoice) -> InvoiceInfo:
    """An invoice flattened: the cents turned into money, the timestamp into ISO."""
    return {
        "id": invoice.id,
        "amount": _money_from_cents(invoice.amount_cents),
        "paid": invoice.paid,
        "issued_at": invoice.issued_at.isoformat(),
    }


def order_list(
    session: SnakeSession,
    *,
    state: OrderState | None = None,
    page: int = 1,
    per_page: int = 20,
) -> OrderListPage:
    """The order listing: a real page of rows, its pager, and the states to filter by.

    TWO statements, always: the count and the page of rows. The filter's options are the enum, so
    there is no third — and that is the difference from the pilot's three, written down here because
    a number that differs for a reason is worth telling apart from one that differs by accident.
    Neither statement depends on how many rows come back, which is what the budget test asserts by
    building the same page at two sizes rather than against a literal.

    It never returns a `Failure`. A filter that matches nothing is an answer, and the page says zero.
    """
    result = usecases.paginate_orders(
        session, state=state, page=page, per_page=per_page
    )
    return {
        "rows": [_order_row(order) for order in result.rows],
        "states": _state_options(),
        "state": state.value if state is not None else "",
        "page": result.page,
        "pages": result.pages,
        "total": result.total,
        "has_prev": result.page > 1,
        "has_next": result.page < result.pages,
        # Clamped rather than `page ± 1`: on the edges the template would otherwise be handed a page
        # number that does not exist and asked to remember not to link it.
        "prev_page": max(1, result.page - 1),
        "next_page": min(result.pages, result.page + 1),
    }


def order_detail(session: SnakeSession, order_id: int) -> OrderDetailPage | Failure:
    """One order: its row, its three to-one relations, its lines and its invoice. THREE statements.

    Three and not two, and the third is a repeat: `order_lines` checks the order exists before it
    reads them, which `get_order` has just done. That is the price of going through the use-case seam
    instead of around it, and it is a fixed price — the number does not move with the size of the
    order, which is the property that matters.
    """
    order = usecases.get_order(session, order_id)
    if isinstance(order, Failure):
        return order
    lines = usecases.order_lines(session, order_id)
    if isinstance(lines, Failure):
        return lines
    return {
        "order": _order_row(order),
        "lines": [_line_row(line) for line in lines],
        "lines_total": _money(
            sum((line.unit_price * line.quantity for line in lines), Decimal("0"))
        ),
        "invoice": _invoice_info(order.invoice) if order.invoice is not None else None,
    }


# ---- The customer sheet ------------------------------------------------------------------------


class CustomerOrderRow(TypedDict):
    """One of a customer's orders WITH WHAT WAS ON IT, and DELIBERATELY without the two parties.

    It is not an `OrderRow` short of a few keys. `_order_row` reads `order.customer` and
    `order.warehouse`, and the query behind this page loads neither: it spends its extra statement on
    the LINES instead, which is the half a sheet of one customer's orders is actually about. Calling
    it here would raise `SnakeRelationshipNotLoaded` rather than run slowly — this ORM shouts instead
    of firing the query nobody asked for. The customer is named ONCE, in the header, because every
    row on the page belongs to the same one; the warehouse is not on the page at all, because
    "which shed did it ship from" is not the question this page was opened to answer.

    The three `can_*` booleans are missing for the same kind of reason and it is worth saying out
    loud: this is a HISTORY, not a place operations are offered from. `orders/operate` is where a
    button lives, and putting one here would be offering an action from a page that has not read the
    stock it depends on.

    `lines_total` sits next to `total` exactly as it does on the order sheet: the first is added up
    from the lines that are on the page, the second is the column the writes keep in step, and
    showing both is how a reader sees that a stored derived value is a claim somebody has to hold to.
    """

    id: int
    reference: str
    state: str
    state_label: str
    total: str
    lines_total: str
    placed_at: str
    has_invoice: bool
    line_count: int
    lines: list[OrderLineRow]


class CustomerSheetPage(TypedDict):
    """Everything one customer has ordered, and what was on each of those orders.

    `order_count` and `ordered_total` come from the SAME statement that draws the report's customer
    table, which is the row this page is reached from. That is why they are here rather than added up
    from `orders` below: the figure on the row somebody clicked and the figure in the heading they
    land on are then the same figure, computed once by the engine, and they cannot drift into an
    argument about whether a cancelled order counts.

    A customer with no orders is a page with an empty list and a heading, never a 404. The 404 is for
    a customer that does not exist, and `orders_of_customer` is what tells the two apart.
    """

    customer_id: int
    username: str
    order_count: int
    ordered_total: str
    orders: list[CustomerOrderRow]


def _named_line_row(line: OrderLine, sku_name: str) -> OrderLineRow:
    """A line flattened into the SHAPE `_line_row` builds, with the name coming from a lookup.

    Same shape and a different builder, which is the whole point of the shape being declared once: a
    template that can print an order's lines can print these, and it never has to know that one query
    included the SKU and the other did not.
    """
    return {
        "sku_id": line.sku_id,
        "sku_name": sku_name,
        "quantity": line.quantity,
        "unit_price": _money(line.unit_price),
        "line_total": _money(line.unit_price * line.quantity),
    }


def _customer_order_row(order: Order, names: dict[int, str]) -> CustomerOrderRow:
    """An order flattened with its lines, hopping NO to-one relation of its own."""
    lines = list(order.lines)
    return {
        "id": order.id,
        "reference": order.reference,
        "state": order.state.value,
        "state_label": state_label(order.state),
        "total": _money(order.total),
        "lines_total": _money(
            sum((line.unit_price * line.quantity for line in lines), Decimal("0"))
        ),
        "placed_at": order.placed_at.isoformat(),
        "has_invoice": order.invoice_id is not None,
        "line_count": len(lines),
        "lines": [_named_line_row(line, names[line.sku_id]) for line in lines],
    }


def customer_sheet(
    session: SnakeSession, customer_id: int
) -> CustomerSheetPage | Failure:
    """One customer's whole order history with every line on it. FIVE statements, whatever the history.

    The five are the probe `orders_of_customer` makes before it reads, the orders, the lines of ALL
    of them in one select-in, the customer table the heading is taken from, and the SKU catalogue the
    line names come out of. None of them grows with the number of orders, and that is what this page
    is for: the same answer read one order at a time is one request per order, which is the shape the
    pages had before this one existed.

    THE ORDER OF THE CALLS IS THE 404. `orders_of_customer` goes first so that an unknown customer is
    refused before anything else is read; the two catalogues below it are only worth fetching for a
    customer that turned out to exist.

    Both lookups are indexed directly and a miss is a `KeyError`, on purpose. `names` is keyed by the
    SKU of a line, whose foreign key the engine enforces, and `stats` by a customer the call above
    has just proved is there — so a miss means two statements disagreeing about the same database,
    which is worth a stack trace rather than a heading with a blank name in it.
    """
    orders = usecases.orders_of_customer(session, customer_id)
    if isinstance(orders, Failure):
        return orders
    by_customer = {row.customer.id: row for row in usecases.customer_orders(session)}
    stats = by_customer[customer_id]
    names = {sku.id: sku.name for sku in inventory_usecases.list_skus(session)}
    return {
        "customer_id": customer_id,
        "username": stats.customer.username,
        "order_count": stats.order_count,
        "ordered_total": _money(Decimal(str(stats.ordered_total or 0))),
        "orders": [_customer_order_row(order, names) for order in orders],
    }


def order_form(
    session: SnakeSession, order_id: int | None = None
) -> OrderFormPage | Failure:
    """The form for `create` and for `update`: same three option lists, with or without an order.

    Creating costs THREE statements — the customers, the warehouses, the SKUs — and editing costs
    three more for the order and its lines. None of the six grows with anything the page shows.

    The customers come from `customer_orders`, which is the only use case in this domain that lists
    them, and it answers their order counts in the same statement. Reading them another way would
    mean a second question to the database for something already on the table.
    """
    order: Order | None = None
    lines: list[OrderLine] = []
    if order_id is not None:
        found = usecases.get_order(session, order_id)
        if isinstance(found, Failure):
            return found
        found_lines = usecases.order_lines(session, order_id)
        if isinstance(found_lines, Failure):
            return found_lines
        order, lines = found, found_lines
    return {
        "customers": [
            _customer_option(row) for row in usecases.customer_orders(session)
        ],
        "warehouses": [
            _warehouse_option(warehouse)
            for warehouse in inventory_usecases.list_warehouses(session)
        ],
        "skus": [_sku_option(sku) for sku in inventory_usecases.list_skus(session)],
        "order": _order_row(order) if order is not None else None,
        "lines": [_line_row(line) for line in lines],
        "is_update": order is not None,
    }


def order_delete_confirm(
    session: SnakeSession, order_id: int
) -> OrderDeletePage | Failure:
    """The confirmation page: the order about to go, and the lines that would go with it.

    THREE statements, and it FETCHES the lines rather than counting them — the opposite of the
    pilot's choice, for the reason `OrderDeletePage` gives. `can_delete` mirrors `remove_order`: an
    order with lines is a `conflict`, and the useful thing to tell somebody looking at it is that
    cancelling is the operation they actually want.
    """
    order = usecases.get_order(session, order_id)
    if isinstance(order, Failure):
        return order
    lines = usecases.order_lines(session, order_id)
    if isinstance(lines, Failure):
        return lines
    can_delete = not lines
    return {
        "order": _order_row(order),
        "lines": [_line_row(line) for line in lines],
        "line_count": len(lines),
        "can_delete": can_delete,
        "blocked": ""
        if can_delete
        else (
            f"This order still has {len(lines)} line(s), and deleting it would orphan them. "
            "An order that has been placed is cancelled, not deleted."
        ),
    }


def _reserve_blocked(order: Order, lines: list[OrderLine]) -> str:
    """Why a reservation is not offered, in the order `reserve` refuses in. Empty when it is offered."""
    if order.state not in _RESERVABLE:
        return (
            f"Only a draft order can be reserved, and this one is "
            f"{state_label(order.state).lower()}."
        )
    if not lines:
        return "An order with no lines has nothing to reserve."
    return ""


def _attach_blocked(order: Order, invoices: list[Invoice]) -> str:
    """Why billing against an existing invoice is not offered. Empty when it is.

    The second reason is the one only this page can see, and it is the same shape as `settle`'s: the
    invoice has to BE there, so a customer with none has nothing to bill against and the operation
    would answer `not_found` after the button was pressed.
    """
    if order.state not in _ATTACHABLE:
        return (
            f"Only an open order can be billed against an invoice, and this one is "
            f"{state_label(order.state).lower()}."
        )
    if not invoices:
        return "This customer has no invoice yet. Settling issues one; this operation reuses one."
    return ""


def _settle_blocked(order: Order, subscriptions: list[Subscription]) -> str:
    """Why a settlement is not offered. Empty when it is.

    The second reason is the one only this page can see: `settle` issues the invoice against a
    subscription of the ORDER'S OWN customer, so a customer without one has nothing to be billed
    through and the operation would answer `not_found` after the button was pressed.
    """
    if order.state not in _SETTLEABLE:
        return (
            f"Only a reserved order can be settled, and this one is "
            f"{state_label(order.state).lower()}."
        )
    if not subscriptions:
        return "This customer has no subscription, and the invoice has to be issued against one."
    return ""


def _cancel_blocked(order: Order) -> str:
    """Why a cancellation is not offered. Empty when it is.

    The two refusals are different answers and not one message with a state in it. Undoing money is a
    refund and undoing nothing is not an operation at all, and telling somebody which of the two they
    are looking at is the entire value of the sentence.
    """
    if order.state is OrderState.CANCELLED:
        return "This order is already cancelled."
    if order.state not in _CANCELLABLE:
        return (
            "This order has been billed. Undoing that is a refund, which is a different "
            "operation with its own money in it."
        )
    return ""


def _reserve_warning(short: int) -> str:
    """The sentence a shortage gets, and the caveat that keeps it a warning rather than a refusal."""
    if short == 0:
        return ""
    counted = "One line wants" if short == 1 else f"{short} lines want"
    return (
        f"{counted} more units than the warehouse has free right now. The reservation reads the "
        "stock again under a row lock and decides there, so this is what it would find, not what "
        "it will answer."
    )


def order_operation(
    session: SnakeSession, order_id: int
) -> OrderOperationPage | Failure:
    """The page that offers `reserve`, `settle`, `cancel` and `attach`, and says why when it does not.

    SEVEN statements, and none of them grows with the number of lines: the order, the existence check
    and the lines, the warehouse's existence check and its whole stock, the customer's subscriptions
    and their invoices. The stock is read for the WAREHOUSE and matched to the lines in Python, which is
    the choice worth naming — a lookup per line would be correct, invisible on a two-line order, and
    an N+1 on the page whose entire subject is what happens under load.

    IT PERFORMS NOTHING, and it must not be called on the way to something that does. Every one of
    the three operations opens by DECLARING its isolation level, which Postgres only accepts before
    the transaction has read anything, and the six statements above read plenty. On a stock server
    that declaration then fails silently rather than loudly, which is why the module docstring spends
    a paragraph on it; the short version is that the GET and the POST get a session each.
    """
    order = usecases.get_order(session, order_id)
    if isinstance(order, Failure):
        return order
    lines = usecases.order_lines(session, order_id)
    if isinstance(lines, Failure):
        return lines
    stock = inventory_usecases.stock_of_warehouse(session, order.warehouse_id)
    if isinstance(stock, Failure):
        # Unreachable through the foreign key, and handled rather than asserted: an `assert` in a
        # page renders as a 500, and a warehouse that has gone missing under a live order is a
        # `not_found` the web layer already knows how to answer.
        return stock
    subscriptions = billing_usecases.subscriptions_of_user(session, order.customer_id)
    # SEVENTH statement, and it is one and not one per subscription: `invoices_of_customer` walks
    # `Invoice.subscription.user_id`, which the emitter plans as a JOIN. Listing them per
    # subscription would be the N+1 this page's whole subject argues against.
    invoices = billing_usecases.invoices_of_customer(session, order.customer_id)

    by_sku = {row.sku_id: row for row in stock}
    rows = [_operation_line_row(line, by_sku.get(line.sku_id)) for line in lines]
    reserve_blocked = _reserve_blocked(order, lines)
    settle_blocked = _settle_blocked(order, subscriptions)
    cancel_blocked = _cancel_blocked(order)
    attach_blocked = _attach_blocked(order, invoices)
    can_reserve = not reserve_blocked
    return {
        "order": _order_row(order),
        "lines": rows,
        "subscriptions": [
            _subscription_option(subscription) for subscription in subscriptions
        ],
        "invoices": [_invoice_info(invoice) for invoice in invoices],
        "can_reserve": can_reserve,
        "can_settle": not settle_blocked,
        "can_cancel": not cancel_blocked,
        "can_attach": not attach_blocked,
        "reserve_blocked": reserve_blocked,
        "settle_blocked": settle_blocked,
        "cancel_blocked": cancel_blocked,
        "attach_blocked": attach_blocked,
        # Only where a reservation is on offer. On an order that already holds its units the
        # arithmetic reads short by design — its own hold is in `held` — and printing a warning
        # about that would be the page alarming somebody about the thing it just did correctly.
        "reserve_warning": _reserve_warning(
            sum(1 for row in rows if row["is_short"]) if can_reserve else 0
        ),
    }


# ---- The report -------------------------------------------------------------------------------------


class CustomerStatsRow(TypedDict):
    """One customer with what they have ordered: the `annotate` row, flattened.

    Both aggregates came back in the SAME statement as the user, one hop away through `User.orders`.
    A customer who has never ordered still appears, with zeroes — which a `GROUP BY` over the orders
    would drop, and which is precisely the row a "who signed up and never bought" question is about.
    """

    id: int
    username: str
    order_count: int
    ordered_total: str


class RepeatCustomerRow(TypedDict):
    """One customer who has ordered more than once: the `GROUP BY` + `HAVING` row.

    It looks like `CustomerStatsRow` and is a different question, which is why it is a different
    shape rather than the same one reused. That one is the roll call and includes the customer with
    zero orders; this one is the set the engine kept after filtering an aggregate BY that aggregate,
    and there is no id in it because a `GROUP BY` on a username has no row to take an id from.
    """

    username: str
    order_count: int
    ordered_total: str


class StateTotalRow(TypedDict):
    """One state with how many orders sit in it and how much money they are worth. Plain `GROUP BY`.

    Grouped by a VALUE and not by a table, which is why the source has no `@snake_result`: there is
    no `states` table to be the row. `state_label` is added here because the enum's value is a
    machine's word and the page is read by a person.
    """

    state: str
    state_label: str
    order_count: int
    total: str


class SequenceRow(TypedDict):
    """One recent order, saying WHICH of that customer's orders it is. The window-function row.

    `nth_for_customer` is the number no other page here can show: it is a fact about the row's
    neighbours (every other order of the same customer) computed without collapsing them. A `1` means
    a first-time buyer and a `9` means a regular, on the same listing, in the same statement.
    """

    reference: str
    customer: str
    placed_at: str
    nth_for_customer: int


class HighlightRow(TypedDict):
    """One order out of the `UNION` of "the biggest" and "the newest". DELIBERATELY THIN.

    There is no customer name and no warehouse code on it, and that is not an omission: a compound
    loads NO relationships — an `include` on a branch is refused when the compound is built — so the
    rows arrive knowing their own columns and nothing else. Flattening a relation here would mean
    firing a query per highlight, which is the exact N+1 this whole layer exists to stop.

    So the shape says what the ORM can actually deliver, rather than what would look nicer. A page
    that wants the customer as well wants a different query, not a different view model.
    """

    id: int
    reference: str
    state: str
    state_label: str
    total: str
    placed_at: str


class BasketRow(TypedDict):
    """One order with WHAT IS ON IT, folded into a single string by the engine.

    `skus` is the only value on this report that is a list flattened rather than a number, and it is
    the one that used to cost a second query and a grouping pass. The names are sorted INSIDE the
    aggregate, so the cell says the same thing on two runs of the same page.
    """

    reference: str
    lines: int
    skus: str


class OrderReportPage(TypedDict):
    """The orders report: five questions, five different parts of the ORM, one page.

    `union_supported` is on the page because these demos are read as documentation and this is the
    one figure on it that depends on the ENGINE rather than on the data. On Postgres and MySQL the
    highlights are one `UNION` of two branches that each keep their own `LIMIT`; on SQLite, which
    refuses parentheses around a compound's branches, they are two statements folded in Python. The
    page can say which happened, and a demo that hides that would be hiding the most interesting
    thing on it.

    `minimum_orders` comes back for the same reason the inventory report returns its threshold: a
    filtered list whose filter is not named is a list nobody can reproduce.
    """

    customers: list[CustomerStatsRow]
    repeat_customers: list[RepeatCustomerRow]
    minimum_orders: int
    states: list[StateTotalRow]
    sequence: list[SequenceRow]
    highlights: list[HighlightRow]
    union_supported: bool
    baskets: list[BasketRow]


def _highlight_row(order: Order) -> HighlightRow:
    """A BARE order flattened. It touches no relationship, because a compound loaded none."""
    return {
        "id": order.id,
        "reference": order.reference,
        "state": order.state.value,
        "state_label": state_label(order.state),
        "total": _money(order.total),
        "placed_at": order.placed_at.isoformat(),
    }


def order_report(
    session: SnakeSession,
    *,
    minimum_orders: int = 2,
    sequence_size: int = 20,
    highlight_size: int = 5,
) -> OrderReportPage:
    """The orders report. SIX statements on Postgres and MySQL, SEVEN on SQLite.

    The extra one is the highlights, and the reason is written out in
    `orders_selectors.order_highlights`: a branch keeps its own `LIMIT` only inside parentheses, and
    SQLite answers `Cap.PARENTHESISED_COMPOUND` with `Nope`. The page reports which path it took
    rather than papering over it.

    It never returns a `Failure`. Every figure is an aggregate, and a shop with no orders yet is an
    answer, not a missing page.
    """
    report = usecases.order_report(
        session,
        minimum_orders=minimum_orders,
        sequence_size=sequence_size,
        highlight_size=highlight_size,
    )
    return {
        "customers": [
            {
                "id": row.customer.id,
                "username": row.customer.username,
                "order_count": row.order_count,
                "ordered_total": _money(Decimal(str(row.ordered_total or 0))),
            }
            for row in report.customers
        ],
        "repeat_customers": [
            {
                "username": username,
                "order_count": placed,
                "ordered_total": _money(spent),
            }
            for username, placed, spent in report.repeat_customers
        ],
        "minimum_orders": minimum_orders,
        "states": [
            {
                "state": state.value,
                "state_label": state_label(state),
                "order_count": placed,
                "total": _money(total),
            }
            for state, placed, total in report.states
        ],
        "sequence": [
            {
                "reference": reference,
                "customer": username,
                "placed_at": placed_at.isoformat(),
                "nth_for_customer": position,
            }
            for reference, username, placed_at, position in report.sequence
        ],
        "highlights": [_highlight_row(order) for order in report.highlights],
        "union_supported": session.dialect.supports_parenthesised_compound,
        "baskets": [
            {"reference": reference, "lines": lines, "skus": skus}
            for reference, lines, skus in report.baskets
        ],
    }


# ---- The export --------------------------------------------------------------------------------------


LINE_EXPORT_HEADER: tuple[str, ...] = (
    "order_id",
    "reference",
    "state",
    "customer",
    "warehouse_code",
    "sku_id",
    "sku_name",
    "quantity",
    "unit_price",
    "line_total",
    "placed_at",
)
"""The columns of the order-lines CSV, with BOTH halves of the line's composite key in it.

`order_id` and `sku_id` are the identity of a line, and a file somebody reconciles against the
database has to be joinable back to it. The reference travels too because it is what a human quotes
on the phone, and an export nobody can talk about is an export nobody uses.
"""


def _line_cells(line: OrderLine) -> tuple[str, ...]:
    """One order line as CSV text: three to-one hops already made, every value already formatted.

    `line.order.customer.username` is read HERE, off a row the query loaded through a to-one
    `include`, and never inside the loop that streams. The multiplication is done here too, for the
    same reason `available` is computed on the stock listing: `quantity * unit_price` is one
    arithmetic, and a formula left to whoever opens the spreadsheet is an arithmetic done two ways.
    """
    order = line.order
    return (
        str(line.order_id),
        order.reference,
        order.state.value,
        order.customer.username,
        order.warehouse.code,
        str(line.sku_id),
        line.sku.name,
        str(line.quantity),
        _money(line.unit_price),
        _money(line.unit_price * line.quantity),
        order.placed_at.isoformat(),
    )


def order_lines_export(
    session: SnakeSession, *, state: OrderState | None = None
) -> CsvExport:
    """Every order line as CSV rows, STREAMED: ONE statement, and memory that does not grow.

    The generator expression is the implementation for the reason
    `inventory_viewmodels.stock_movements_export` spells out: a `yield` here would make the function
    itself lazy, and `iterate`'s refusal of an unstreamable query would stop firing next to the
    mistake that caused it.

    `state` narrows the query and not the writer. Filtering while writing would pull every line of
    every state out of the database in order to throw most of them away — on the one page whose
    entire subject is not pulling things out of the database.
    """
    lines = usecases.stream_order_lines(session, state=state)
    return CsvExport(
        filename="order-lines.csv",
        header=LINE_EXPORT_HEADER,
        rows=(_line_cells(line) for line in lines),
    )
