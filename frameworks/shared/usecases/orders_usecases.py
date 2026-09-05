"""orders domain use cases (orders, their lines and the report over them), written once.

The three frameworks re-export these; none of them holds a line of this logic. What lives here is the
part that is the same everywhere: validate the input, call the services, decide when the operation is
finished and commit ONCE.

`place_order` is the one that earns the layer, and it earns it three times over. It reads across
THREE other domains before it writes anything — the customer from `accounts`, the warehouse and every
SKU from `inventory` — because all three are foreign keys and the engine would refuse anyway, but
from inside a commit, with a driver error, three layers below the form that asked. It copies each
price off its SKU, because a total that arrives from a form is a number the customer chose. And it
writes the order and its lines as ONE unit of work, because an order whose lines landed and whose
total did not is a row that adds up to a lie.

RESERVING UNDER A LOCK AND SETTLING INSIDE A SAVEPOINT ARE HERE, and the condition they waited for
is the one worth restating: they need an end-to-end test against a real Postgres, because SQLite
answers `Nope` to row locking and a `for_update` proved on it would run degraded and go green having
locked nothing. That test is `shared/tests/test_orders_concurrency.py`, and it is red exactly when
the lock is taken out — which is the only way anybody knows it is a lock and not a method named
after one.

Both operations now have an asynchronous twin in `shared/aio/orders_usecases.py`, and it is held to
the same standard: the same file proves the row lock and the savepoint rewind on BOTH colours,
against the same server, side by side.

THE STATES ARE A RULE, AND THE RULE LIVES HERE. `orders_services.set_state` moves an order anywhere
it is told; which moves are legal is decided in this module, because that is the layer that can
answer the caller with a reason instead of a stack trace. Cancelling an order that has already been
billed is not a bug to be prevented by hiding a button, it is a refund — a different operation, with
its own money in it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal

from snakeorm import SnakeIsolation, SnakeSession, SnakeUtc

from shared.models import CustomerOrders, Order, OrderLine, OrderState, Stock
from shared.selectors import billing_selectors, blog_selectors, inventory_selectors
from shared.selectors import orders_selectors as selectors
from shared.services import billing_services, inventory_services
from shared.services import orders_services as services
from shared.usecases.result import Failure

# The states an order can still be edited or cancelled from: nothing has been billed yet. Written
# once as a set rather than as an `in (...)` repeated in four guards, because the day `RESERVED`
# stops being editable it has to stop in all four at the same time.
_OPEN_STATES = frozenset({OrderState.DRAFT, OrderState.RESERVED})


class PaymentDeclined(Exception):
    """What a payment processor saying no looks like from inside `settle`.

    It is an EXCEPTION and not a `Failure` because it is raised by code this repository does not own:
    `settle` hands the charge to a callable, and a callable that fails fails the way Python fails. The
    use case catches it and turns it into a `Failure` at its own boundary, which is where every other
    refusal in this layer already lives.

    Declared rather than caught as a bare `Exception`, and that distinction is the whole guard. The
    savepoint rewinds the billing for ANY exception, but only this one gets compensated and answered:
    a `KeyError` from a bug is not a declined card, and dressing it up as one would return a tidy 402
    for something that needs a stack trace.
    """


Charge = Callable[[Decimal], None]
"""Taking the money. It gets an amount and either returns or raises `PaymentDeclined`.

The one step of `settle` that is not a database write, and therefore the one this repository cannot
implement. Typed as a parameter instead of imagined as a stub inside the operation, because the
alternative is an operation whose failure path is unreachable without breaking the database on
purpose — which is how a savepoint ends up being tested by proving that the method exists.
"""


def accept_every_charge(amount: Decimal) -> None:
    """The demos' payment processor: there is not one, so every charge goes through.

    It takes the amount and ignores it, and it is a named function rather than a lambda default so
    that the thing missing from these demos has somewhere to be read about.
    """


def _open_stock_transaction(session: SnakeSession) -> None:
    """Opens the transaction the three stock-touching operations share, and DECLARES what it sees.

    It has to be the first thing any of them does. `SET TRANSACTION` is only valid as the first
    statement of a transaction — Postgres answers `ActiveSqlTransaction` once the database has been
    touched — so this is a precondition on the caller as much as a line of code: `reserve`, `settle`
    and `cancel_order` must be handed a session with no transaction in flight.

    WHY `READ COMMITTED` AND NOT NOTHING AT ALL, measured rather than assumed. Under `REPEATABLE READ`
    a locking read of a row another transaction has just updated does not wait and then decide: it
    dies with `could not serialize access due to concurrent update`. So the second customer would get
    a driver error where the operation means to answer `conflict`. `READ COMMITTED` is what the
    lock-then-decide shape needs, and it is not something to take for granted from the engine: it is
    Postgres's default but a server-wide setting (`default_transaction_isolation`) can move it, and
    MySQL — which these demos also run on — defaults to `REPEATABLE READ`.

    ASKING THE ENGINE, and asking about the right thing. The gate is row locking, and on the three
    engines here that is exactly the same question: Postgres and MySQL answer `Full` and have
    `SET TRANSACTION`; SQLite answers `Nope` and has no such statement at all. It is not a proxy for
    something else either — SQLite's write transactions hold the whole FILE and are serialisable by
    construction, so there is nothing to reserve and nothing to declare. The operation is not degraded
    there, it is alone with the database.
    """
    if session.dialect.supports_row_locking:
        session.set_isolation(SnakeIsolation.READ_COMMITTED)


def _stock_by_sku(
    session: SnakeSession, *, warehouse_id: int, lines: Sequence[OrderLine]
) -> dict[int, Stock]:
    """The locked stock rows an order takes from, keyed by SKU so a line can find its own.

    ONE statement for the whole order. The dictionary is built here and not in the selector because
    what the selector owns is the QUERY — the filter, the order the locks are taken in — and what
    this owns is that a line and a row find each other. A missing key is a pair the warehouse has
    never held, which each caller reads differently: a shortage for `reserve`, an impossibility for
    `settle`, and nothing to give back for `cancel_order`.
    """
    rows = inventory_selectors.lock_stock(
        session,
        warehouse_id=warehouse_id,
        sku_ids=[line.sku_id for line in lines],
    )
    return {row.sku_id: row for row in rows}


def _in_cents(total: Decimal) -> int:
    """The order's money in the shape `billing` stores it. The two domains disagree, and this is the seam.

    An order's `total` is a `NUMERIC(12,2)` because that is what money is; an invoice's `amount_cents`
    is an integer count of cents, chosen so it is exact on every engine without a decimal type. Both
    are defensible and they are not the same thing, so the conversion is written ONCE, here, where the
    two domains meet. Spelling `int(total * 100)` at each call site is how the day comes that one of
    them rounds and another truncates.
    """
    return int((total * 100).to_integral_value())


def list_orders(
    session: SnakeSession, *, state: OrderState | None = None
) -> list[Order]:
    """Every order with its customer, warehouse and invoice loaded, optionally narrowed to a state."""
    return selectors.list_orders(session, state=state)


@dataclass(frozen=True, slots=True)
class OrderPage:
    """One page of orders together with everything the pager needs to draw itself.

    The four travel together because they are ONE answer. Handing back only the rows makes the caller
    ask for the total separately, and the caller that asks separately is the one that filters the two
    questions differently — a pager reading "47 orders" over a listing that shows a different 47.

    `page` is the CLAMPED page and not the one that was asked for, which is the whole reason it comes
    back at all: the number arrives from a URL, so it is whatever somebody typed there.
    """

    rows: list[Order]
    total: int
    page: int
    pages: int


def paginate_orders(
    session: SnakeSession,
    *,
    state: OrderState | None = None,
    customer_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> OrderPage:
    """A page of orders, optionally narrowed. TWO statements, whatever the size of the history.

    Both numbers get clamped, since both arrive from a URL: `per_page=0` is a division by zero and
    `page=99` is a stale bookmark, and neither should be a stack trace.

    An unknown `customer_id` gives an EMPTY page rather than `Failure("not_found")`. A filter is a
    filter: answering "nothing matches" is correct, and probing that the customer exists would add a
    third statement to every listing to catch a case only a hand-edited URL produces.
    """
    per_page = max(1, per_page)
    total = selectors.count_orders(session, state=state, customer_id=customer_id)
    pages = max(1, -(-total // per_page))
    page = min(max(1, page), pages)
    rows = selectors.orders_page(
        session,
        state=state,
        customer_id=customer_id,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return OrderPage(rows=rows, total=total, page=page, pages=pages)


def get_order(session: SnakeSession, order_id: int) -> Order | Failure:
    """One order with its three parties loaded; `not_found` if it does not exist."""
    order = selectors.get_order_with_parties(session, order_id)
    return order if order is not None else Failure("not_found")


def order_lines(session: SnakeSession, order_id: int) -> list[OrderLine] | Failure:
    """An order's lines with the SKU loaded; `not_found` if the order does not exist.

    The existence check is a statement this could skip, and it is not skipped: an endpoint that got
    the id from a URL has to answer 404, and an order with no lines and an order that never existed
    are the same empty list otherwise.
    """
    if selectors.get_order(session, order_id) is None:
        return Failure("not_found")
    return selectors.lines_of_order(session, order_id)


def orders_of_customer(
    session: SnakeSession, customer_id: int
) -> list[Order] | Failure:
    """A customer's orders with each order's lines loaded; `not_found` if the customer does not exist."""
    if blog_selectors.get_user(session, customer_id) is None:
        return Failure("not_found")
    return selectors.orders_with_lines(session, customer_id)


def orders_per_state(session: SnakeSession) -> list[tuple[OrderState, int, Decimal]]:
    """How many orders and how much money sit in each state. One row per state, one statement."""
    return selectors.orders_per_state(session)


def customer_orders(session: SnakeSession) -> list[CustomerOrders]:
    """Every customer with their order count and what they have spent, typed, in one statement."""
    return selectors.customer_orders(session)


def place_order(
    session: SnakeSession,
    *,
    reference: str,
    customer_id: int,
    warehouse_id: int,
    lines: Sequence[tuple[int, int]],
) -> Order | Failure:
    """Places an order: validates, prices every line off its SKU, writes it all and commits ONCE.

    `lines` is a sequence of `(sku_id, quantity)` — the pair the composite key is made of, which is
    also the only shape that cannot express a duplicate ambiguously. A repeat of the same SKU is
    `missing_fields` and not a silent merge: the caller sent a form that says two different things
    about one SKU, and guessing which one it meant is how an order ships half of what was asked for.

    The order of the refusals is deliberate. The shape first (`missing_fields`, a 400: nothing about
    the database can make an empty order valid), then the three existence checks (`not_found`, a
    404), and the uniqueness of the reference last (`conflict`, a 409) — because it is the only one
    of the four that another request can turn from false to true while this one is running, and the
    unique index is what actually holds it.
    """
    if not reference or not lines:
        return Failure("missing_fields")
    if any(quantity <= 0 for _, quantity in lines):
        return Failure("missing_fields")
    if len({sku_id for sku_id, _ in lines}) != len(lines):
        return Failure("missing_fields")

    if blog_selectors.get_user(session, customer_id) is None:
        return Failure("not_found")
    if inventory_selectors.get_warehouse(session, warehouse_id) is None:
        return Failure("not_found")
    priced: list[tuple[int, int, Decimal]] = []
    for sku_id, quantity in lines:
        sku = inventory_selectors.get_sku(session, sku_id)
        if sku is None:
            return Failure("not_found")
        priced.append((sku_id, quantity, sku.price))

    if selectors.get_order_by_reference(session, reference) is not None:
        return Failure("conflict")

    total = sum((price * quantity for _, quantity, price in priced), Decimal("0"))
    order = services.create_order(
        session,
        reference=reference,
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        total=total,
    )
    services.add_lines(
        session,
        [
            OrderLine(
                order_id=order.id,
                sku_id=sku_id,
                quantity=quantity,
                unit_price=price,
            )
            for sku_id, quantity, price in priced
        ],
    )
    session.commit()
    return order


def set_line(
    session: SnakeSession, *, order_id: int, sku_id: int, quantity: int
) -> OrderLine | Failure:
    """States how many units of a SKU an order wants, adding the line if it was not there.

    Zero is `missing_fields` and not a shortcut for deleting the line. Deleting is `remove_line`, and
    conflating them means a form that submits an empty box silently drops a line the customer never
    said to drop.

    An order that has been billed is a `conflict`: its lines are what the invoice was calculated
    from, so changing them would leave the invoice describing an order that no longer exists.
    """
    if quantity <= 0:
        return Failure("missing_fields")
    order = selectors.get_order(session, order_id)
    if order is None:
        return Failure("not_found")
    if order.state not in _OPEN_STATES:
        return Failure("conflict")
    sku = inventory_selectors.get_sku(session, sku_id)
    if sku is None:
        return Failure("not_found")

    services.set_line(
        session,
        order_id=order_id,
        sku_id=sku_id,
        quantity=quantity,
        unit_price=sku.price,
    )
    _retotal(session, order)
    session.commit()
    line = selectors.get_line(session, order_id, sku_id)
    assert line is not None
    return line


def remove_line(session: SnakeSession, *, order_id: int, sku_id: int) -> None | Failure:
    """Removes one line from an order and leaves the total derived. `not_found` if the pair is not there.

    Both halves of the key are required. With one order in the database, a delete that quietly
    dropped `order_id` removes the right row; it only breaks once there is a second one.
    """
    line = selectors.get_line(session, order_id, sku_id)
    if line is None:
        return Failure("not_found")
    order = selectors.get_order(session, order_id)
    if order is None:
        return Failure("not_found")
    if order.state not in _OPEN_STATES:
        return Failure("conflict")

    services.delete_line(session, line)
    _retotal(session, order)
    session.commit()
    return None


def cancel_order(session: SnakeSession, *, order_id: int) -> Order | Failure:
    """Cancels an open order, giving back whatever it was holding. `conflict` once it has been billed.

    The two open states cancel DIFFERENTLY, and that difference is the whole reason `OrderState` is an
    enum and not a `cancelled` boolean. From `DRAFT` nothing was ever promised, so there is nothing to
    give back and giving something back would invent units the warehouse never had. From `RESERVED`
    the hold has to be released, or the shelf stays full while the warehouse starts refusing orders it
    could fill — the expensive kind of wrong, because `quantity` is right the whole time and nothing
    looks broken.

    A boolean cannot tell those two apart. Whichever way it guessed, one of the two would be wrong
    every time, and neither would fail loudly.

    Once the order has been billed this refuses: undoing money is a refund and undoing a shipment is a
    return, and neither is what this does. `conflict` is the operation saying it is the wrong tool.

    A cancellation is a STATE and not a deletion: the order is history from the moment it exists, and
    a customer asking why their order vanished is a question the database should be able to answer.
    """
    _open_stock_transaction(session)
    order = selectors.get_order(session, order_id)
    if order is None:
        session.rollback()
        return Failure("not_found")
    if order.state not in _OPEN_STATES:
        session.rollback()
        return Failure("conflict")

    if order.state is OrderState.RESERVED:
        lines = selectors.bare_lines_of_order(session, order_id)
        held = _stock_by_sku(session, warehouse_id=order.warehouse_id, lines=lines)
        for line in lines:
            row = held.get(line.sku_id)
            if row is not None:
                inventory_services.release_units(
                    session, stock=row, units=line.quantity
                )
    services.set_state(session, order=order, state=OrderState.CANCELLED)
    session.commit()
    return order


def reserve(session: SnakeSession, *, order_id: int) -> Order | Failure:
    """Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK. All of them or none.

    This is the operation the domain was built around, and the one place in these demos where two
    people want the same thing at the same time. Without the lock both customers read the same
    availability, both find one unit free, both write, and the same unit is promised twice — a bug
    with no symptom: each half of the arithmetic is right on its own, and the two numbers only
    disagree with the shelf.

    THREE THINGS MAKE IT WORK, and every one of them is a decision.

    The ISOLATION is declared FIRST, before any read, because `SET TRANSACTION` is only valid as the
    first statement of a transaction and Postgres answers `ActiveSqlTransaction` once the database has
    been touched. That is a precondition on the caller: this operation must be handed a session with
    no transaction in flight. And the level is not decoration — measured, under `REPEATABLE READ` the
    second customer's locking read does not wait and refuse, it dies with `could not serialize access
    due to concurrent update`. `READ COMMITTED` is what makes "wait for the lock, then decide against
    what the winner left behind" the actual behaviour, and the level is a server setting the operation
    does not get to assume: MySQL's default is `REPEATABLE READ`.

    The LOCK is taken over every line in ONE statement, in a fixed order — see
    `inventory_selectors.lock_stock`. One statement so the rows are taken together, fixed order so two
    orders wanting the same two SKUs cannot each hold what the other waits for.

    The DECISION comes before any write. Availability is `quantity - reserved`, counting what is
    already promised and not only what is on the shelf, and one short line refuses the WHOLE order: a
    partial reservation is not a state this domain has, and units held for an order that will never
    ship are indistinguishable from units held for one that will.

    A refusal ROLLS BACK rather than merely returning. It wrote nothing, but it is holding row locks,
    and a refusal that walks away still holding them blocks the next customer until the connection is
    returned to the pool — a hang whose cause is three layers away from where it shows up.
    """
    _open_stock_transaction(session)
    order = selectors.get_order(session, order_id)
    if order is None:
        session.rollback()
        return Failure("not_found")
    if order.state is not OrderState.DRAFT:
        session.rollback()
        return Failure("conflict")

    lines = selectors.bare_lines_of_order(session, order_id)
    if not lines:
        session.rollback()
        return Failure("conflict")
    held = _stock_by_sku(session, warehouse_id=order.warehouse_id, lines=lines)
    for line in lines:
        row = held.get(line.sku_id)
        # A pair with no row holds ZERO, which is a shortage like any other. It is not `not_found`:
        # the order exists, the SKU exists, and what the caller asked is whether there are enough.
        if row is None or row.on_hand - row.reserved < line.quantity:
            session.rollback()
            return Failure("conflict")

    for line in lines:
        row = held[line.sku_id]
        inventory_services.hold_units(session, stock=row, units=line.quantity)
    services.set_state(session, order=order, state=OrderState.RESERVED)
    session.commit()
    return order


def settle(
    session: SnakeSession,
    *,
    order_id: int,
    subscription_id: int,
    method: str = "card",
    charge: Charge = accept_every_charge,
) -> Order | Failure:
    """Bills a RESERVED order, takes the money and ships it. FOUR steps, and one of them can say no.

    The flow is `RESERVED` -> the invoice is issued -> the money is taken -> the units leave ->
    `SETTLED`. What makes it worth writing is not the happy path, it is the shape of the failure: the
    invoice belongs to `billing` and the money belongs to nobody in this repository, so this operation
    cannot enumerate the ways its middle can fail. What it CAN do is bound them.

    THE SAVEPOINT, and what is deliberately outside it. Issuing the invoice happens BEFORE the
    savepoint and survives whatever follows, because an issued invoice is a document and not a wish:
    a customer who has been sent a bill has been sent a bill, and making it evaporate because a card
    was declined leaves the order and the accounts telling different stories. Everything after it is
    inside — the payment, the shipment, the final state — because those are the ones that must not
    exist if the money did not arrive.

    The payment row is written BEFORE the processor answers, on purpose, and the savepoint is exactly
    what makes that safe. The other order — charge first, record after — has a window in which the
    money has been taken and nothing in the database says so, and no rollback can fix that one.

    WHAT A ROLLBACK TO SAVEPOINT DOES NOT UNDO, which is the thing that cost the most to learn here:
    it rewinds the DATABASE, not the Python objects. This ORM has no identity map and no unit of work
    by design, so the `Stock` instances the shipment mutated still carry the shipped numbers after the
    rewind, while the rows behind them are back to what they were. The compensation therefore RE-READS
    the rows instead of writing arithmetic on top of values that no longer exist. Trusting the objects
    gives no error at all: it commits a `reserved` computed from a state that was rolled back.

    And AFTER the rewind the transaction is still alive, which is the whole reason a savepoint is the
    tool and not a `rollback()`. In Postgres a failed statement poisons the transaction — every
    statement after it answers `current transaction is aborted` — so without the savepoint the
    release could not be written at all, and a plain `rollback()` would throw away the invoice as
    well. The units would stay held by an order that is never going to ship, and nothing would say so.

    The `charge` is a parameter because taking money is the one step here that is not a database
    write. The demos have no payment processor, so the default accepts everything; what the parameter
    buys is that the declined path is reachable without breaking the database on purpose.
    """
    _open_stock_transaction(session)
    order = selectors.get_order(session, order_id)
    if order is None:
        session.rollback()
        return Failure("not_found")
    if order.state is not OrderState.RESERVED:
        session.rollback()
        return Failure("conflict")
    subscription = billing_selectors.get_subscription(session, subscription_id)
    if subscription is None:
        session.rollback()
        return Failure("not_found")
    # Nothing in the schema stops an order pointing at somebody else's invoice — `Order.invoice_id`
    # does not know whose subscription the invoice hangs off — so the rule can only live here. It
    # guards the one query no report recovers from: money added up across two people who never met.
    if subscription.user_id != order.customer_id:
        session.rollback()
        return Failure("conflict")

    lines = selectors.bare_lines_of_order(session, order_id)
    held = _stock_by_sku(session, warehouse_id=order.warehouse_id, lines=lines)
    if any(line.sku_id not in held for line in lines):
        session.rollback()
        return Failure("conflict")

    invoice = billing_services.issue_invoice(
        session, subscription_id, _in_cents(order.total)
    )
    services.attach_invoice(session, order=order, invoice_id=invoice.id)
    try:
        with session.savepoint():
            billing_services.pay_invoice(session, invoice.id, method)
            charge(order.total)
            for line in lines:
                inventory_services.ship_held(
                    session, stock=held[line.sku_id], units=line.quantity
                )
            services.set_state(session, order=order, state=OrderState.SETTLED)
    except PaymentDeclined:
        # The rewind took the payment, the shipment and the state with it. The invoice stayed, and so
        # did the transaction, which is what lets the release be written at all. The rows are read
        # AGAIN because the instances above are stale in the one direction that does not raise.
        fresh = _stock_by_sku(session, warehouse_id=order.warehouse_id, lines=lines)
        for line in lines:
            inventory_services.release_units(
                session, stock=fresh[line.sku_id], units=line.quantity
            )
        session.commit()
        return Failure("payment_declined")
    session.commit()
    return order


def attach_invoice(
    session: SnakeSession, *, order_id: int, invoice_id: int
) -> Order | Failure:
    """Bills an open order against an existing invoice and moves it to `INVOICED`.

    This is the JOINT with `billing`, and the plain half of it: it links the two rows and stops. The
    half that can fail halfway — issuing the invoice, taking the payment and releasing the
    reservation if the payment does not land — is `settle` above, and that one needs a savepoint.

    The invoice is looked up rather than trusted, so a stale id from a form is a `not_found` here
    instead of a foreign key violation raised inside the commit.
    """
    order = selectors.get_order(session, order_id)
    if order is None:
        return Failure("not_found")
    if order.state not in _OPEN_STATES:
        return Failure("conflict")
    if billing_selectors.get_invoice(session, invoice_id) is None:
        return Failure("not_found")
    services.attach_invoice(session, order=order, invoice_id=invoice_id)
    session.commit()
    return order


def remove_order(session: SnakeSession, *, order_id: int) -> None | Failure:
    """Deletes an order. `not_found` if it is not there, `conflict` if its lines would be orphaned.

    The refusal is the interesting half, and it is the same FK-restrict-versus-cascade path the
    inventory's `remove_stock` walks from the other side. The engine would refuse anyway — with a
    driver error, from inside a commit. Checking first turns that into something a delete page can
    explain: an order that has lines gets cancelled, not deleted.
    """
    order = selectors.get_order(session, order_id)
    if order is None:
        return Failure("not_found")
    if selectors.count_lines_of(session, order_id) > 0:
        return Failure("conflict")
    services.delete_order(session, order)
    session.commit()
    return None


def _retotal(session: SnakeSession, order: Order) -> None:
    """Re-derives the order's total from the lines currently in the transaction.

    It re-reads them instead of taking the caller's word: the writes above went through an upsert and
    a delete, so what the order now holds is what the database says it holds, not what the caller
    thought it was writing. One extra statement per edit, and it is what keeps the stored total from
    being right exactly once — on creation — and silently wrong from the first edit onwards.
    """
    services.retotal(
        session, order=order, lines=selectors.lines_of_order(session, order.id)
    )


@dataclass(frozen=True, slots=True)
class OrderReport:
    """The four answers the orders report is made of, gathered into one value.

    Same bargain as `inventory_usecases.StockReport`: one value, four figures, each one a different
    part of the ORM. `customers` is `annotate`, `repeat_customers` is `GROUP BY` + `HAVING`, `states`
    is a plain `GROUP BY`, `sequence` is a window function and `highlights` is a `UNION` of two
    bounded branches.

    `highlights` carries BARE orders, and that is a fact about compounds rather than an oversight: a
    `UNION` loads no relationships at all —an `include` on a branch is rejected when the compound is
    built— so these rows know their own columns and nothing else. The view model's highlight shape is
    built for exactly that, which is why it shows a reference and a total and no customer name.
    """

    customers: list[CustomerOrders]
    repeat_customers: list[tuple[str, int, Decimal]]
    states: list[tuple[OrderState, int, Decimal]]
    sequence: list[tuple[str, str, SnakeUtc, int]]
    highlights: list[Order]
    # Every order with WHAT IS ON IT, folded into one cell. It is the only figure here that is
    # not a number, and that is the point of it: a basket is a LIST, and the alternative to
    # asking the engine to fold it was a second query plus a pass in Python.
    baskets: list[tuple[str, int, str]]


def order_report(
    session: SnakeSession,
    *,
    minimum_orders: int = 2,
    sequence_size: int = 20,
    highlight_size: int = 5,
) -> OrderReport:
    """The whole orders report. SIX statements on Postgres and MySQL, SEVEN on SQLite.

    The difference is `highlights` and it is declared rather than hidden: the compound needs
    parentheses to keep a `LIMIT` inside a branch, SQLite refuses them, and `order_highlights` falls
    back to two statements folded in Python. Both numbers are pinned by the budget tests, which is
    the only honest way to write down a cost that depends on the engine — a single literal would be
    a lie on two of the three.

    Everything else is flat: not one of the six depends on how many orders exist, and the two that
    could —the sequence strip and the highlights— carry their own `LIMIT`.
    """
    return OrderReport(
        customers=selectors.customer_orders(session),
        repeat_customers=selectors.repeat_customers(
            session, minimum_orders=minimum_orders
        ),
        states=selectors.orders_per_state(session),
        sequence=selectors.order_sequence(session, limit=sequence_size),
        highlights=selectors.order_highlights(session, size=highlight_size),
        baskets=selectors.order_baskets(session),
    )


def stream_order_lines(
    session: SnakeSession, *, state: OrderState | None = None
) -> Iterator[OrderLine]:
    """The order lines as a STREAM, for the export. `return`, never `yield`.

    The same discipline `inventory_usecases.stream_movements` spells out, and the same reason for
    stating it twice: these are the two places a `for` loop would look harmless and would turn the
    export back into something that materialises. An unknown state is no filter at all rather than a
    `Failure`, which is what `orders_viewmodels.parse_state` already decided for the listing.
    """
    return selectors.stream_order_lines(session, state=state)
