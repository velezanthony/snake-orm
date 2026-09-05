"""orders domain (orders, their lines, the stock they hold and the money they settle), asked of an
`AsyncSession`.

The twin of `shared/usecases/orders_usecases.py`: same names, same parameters, same answers —
including the same `Failure` reasons, because a reason is what the user reads and two wordings of
one refusal is the drift this package's nets exist to catch.

WHY THIS DOMAIN IS THE ONE WORTH TWINNING, and it is not for the endpoint count. The other eight
twins are reads and plain writes; this one is the only place where the ASYNCHRONOUS session is asked
to do the three things it was built for and nothing else exercises. `reserve` declares an isolation
level and takes a row lock; `settle` opens a savepoint, lets it rewind and keeps writing inside the
same transaction afterwards. Before this module `AsyncSession.set_isolation` and
`AsyncSession.savepoint` had no caller outside `src/test` — which is to say the two hardest things
in the asynchronous session were exercised by tests that call them and by no application that needs
them. That is exactly the state the demos exist to leave behind.

THE QUERIES ARE NOT REBUILT HERE. Every fragment comes from the synchronous selectors, unchanged,
because a `SnakeQuery` has no colour — including the LOCKING read, which is
`inventory_selectors.locking_stock_query` and takes the DIALECT rather than a session precisely so
that both colours ask the engine the same question and lock the same rows in the same order. The SQL
of this module and of its twin is therefore identical by construction rather than by agreement.

WHAT DOES GET WRITTEN TWICE is the control flow and the writes, because `await` is syntax: a service
runs a statement, so it has a colour, and `shared/services/` serves the synchronous half. The bodies
below inline the same three or four lines each service holds.

`accept_every_charge` IS A COROUTINE HERE, and that is not a formality imposed by the mirror net.
Taking money is the one step of `settle` that is not a database write, which in a real application
means an HTTP call to a processor — the exact shape of I/O this whole layer exists to stop blocking
on. A synchronous default would have made the demo's one non-database dependency the one thing that
stalls the loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from decimal import Decimal

from snakeorm import AsyncSession, SnakeIsolation, SnakeUtc

from shared.models import (
    CustomerOrders,
    Invoice,
    Order,
    OrderLine,
    OrderState,
    Stock,
    StockMovement,
    MovementReason,
)
from shared.selectors import blog_selectors, inventory_selectors
from shared.selectors import orders_selectors as selectors
from shared.selectors.billing_selectors import invoice_by_id, subscription_by_id
from shared.services.billing_services import PAYMENT_KINDS
from shared.usecases.orders_usecases import (
    OrderPage,
    OrderReport,
    PaymentDeclined,
    _OPEN_STATES,
)
from shared.usecases.result import Failure

Charge = Callable[[Decimal], Awaitable[None]]
"""Taking the money, awaited. It gets an amount and either returns or raises `PaymentDeclined`.

The asynchronous shape of `orders_usecases.Charge`, and the difference is the point rather than an
artefact: the synchronous demos hand `settle` a blocking callable because their session blocks
anyway, while here the processor is the one dependency that is NOT the database and would hold the
loop for every other request while it waited.
"""


async def accept_every_charge(amount: Decimal) -> None:
    """The demos' payment processor: there is not one, so every charge goes through.

    It takes the amount and ignores it, and it is a named coroutine rather than a lambda default so
    that the thing missing from these demos has somewhere to be read about.
    """


async def _open_stock_transaction(session: AsyncSession) -> None:
    """Opens the transaction the three stock-touching operations share, and DECLARES what it sees.

    The asynchronous half of `orders_usecases._open_stock_transaction`, with the same precondition on
    the caller and for the same reason: `SET TRANSACTION` is only valid as the first statement of a
    transaction, so `reserve`, `settle` and `cancel_order` must be handed a session with nothing in
    flight. The gate is row locking, asked of the dialect, which answers identically on both colours
    because it is a fact about the engine and not about how the statement is sent.
    """
    if session.dialect.supports_row_locking:
        await session.set_isolation(SnakeIsolation.READ_COMMITTED)


async def _stock_by_sku(
    session: AsyncSession, *, warehouse_id: int, lines: Sequence[OrderLine]
) -> dict[int, Stock]:
    """The locked stock rows an order takes from, keyed by SKU so a line can find its own.

    ONE statement for the whole order, taken through the same fragment the synchronous path uses, so
    the lock covers the same rows in the same order. A missing key is a pair the warehouse has never
    held, which each caller reads differently.
    """
    rows = await session.all(
        inventory_selectors.locking_stock_query(
            session.dialect,
            warehouse_id=warehouse_id,
            sku_ids=[line.sku_id for line in lines],
        )
    )
    return {row.sku_id: row for row in rows}


def _in_cents(total: Decimal) -> int:
    """The order's money in the shape `billing` stores it, exactly as the synchronous seam does it."""
    return int((total * 100).to_integral_value())


async def _hold_units(session: AsyncSession, *, stock: Stock, units: int) -> None:
    """Promises `units` of an already-loaded pair. It touches `reserved`, never `quantity`."""
    stock.reserved = stock.reserved + units
    await session.update(stock)


async def _release_units(session: AsyncSession, *, stock: Stock, units: int) -> None:
    """Un-promises `units`: the hold goes away and the shelf is untouched."""
    stock.reserved = stock.reserved - units
    await session.update(stock)


async def _ship_held(session: AsyncSession, *, stock: Stock, units: int) -> None:
    """Turns a promise into a shipment: BOTH columns drop, and the movement says why."""
    stock.on_hand = stock.on_hand - units
    stock.reserved = stock.reserved - units
    await session.update(stock)
    await session.add(
        StockMovement(
            stock_warehouse_id=stock.warehouse_id,
            stock_sku_id=stock.sku_id,
            delta=-units,
            reason=MovementReason.SALE,
            note=None,
        )
    )


async def _set_state(
    session: AsyncSession, *, order: Order, state: OrderState
) -> Order:
    """Moves an order to a state. WHICH moves are legal is decided by the use cases, not here."""
    order.state = state
    await session.update(order)
    return order


async def _retotal(session: AsyncSession, order: Order) -> None:
    """Re-derives the order's total from the lines currently in the transaction.

    It RE-READS them rather than taking the caller's word, for the reason the synchronous twin
    spells out: the writes above went through an upsert and a delete, so what the order holds is
    what the database says it holds.
    """
    lines = await session.all(selectors.lines_of(order.id).include(OrderLine.sku))
    order.total = sum((line.unit_price * line.quantity for line in lines), Decimal("0"))
    await session.update(order)


async def list_orders(
    session: AsyncSession, *, state: OrderState | None = None
) -> list[Order]:
    """Every order with its customer, warehouse and invoice loaded, optionally narrowed to a state."""
    return await session.all(
        selectors.with_parties(selectors.order_listing(state=state))
    )


async def paginate_orders(
    session: AsyncSession,
    *,
    state: OrderState | None = None,
    customer_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> OrderPage:
    """A page of orders, optionally narrowed. TWO statements, whatever the size of the history.

    Both numbers get clamped because both arrive from a URL, and an unknown `customer_id` gives an
    EMPTY page rather than `not_found`: a filter is a filter.
    """
    per_page = max(1, per_page)
    total = await session.count(
        selectors.order_listing(state=state, customer_id=customer_id)
    )
    pages = max(1, -(-total // per_page))
    page = min(max(1, page), pages)
    rows = await session.all(
        selectors.with_parties(
            selectors.order_listing(state=state, customer_id=customer_id)
        )
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    return OrderPage(rows=rows, total=total, page=page, pages=pages)


async def get_order(session: AsyncSession, order_id: int) -> Order | Failure:
    """One order with its three parties loaded; `not_found` if it does not exist."""
    order = await session.first(selectors.order_with_parties_by_id(order_id))
    return order if order is not None else Failure("not_found")


async def order_lines(
    session: AsyncSession, order_id: int
) -> list[OrderLine] | Failure:
    """An order's lines with the SKU loaded; `not_found` if the order does not exist.

    The existence check is a statement this could skip and does not, for the reason its twin gives:
    an order with no lines and an order that never existed are the same empty list otherwise.
    """
    if await session.first(selectors.order_by_id(order_id)) is None:
        return Failure("not_found")
    return await session.all(selectors.lines_of(order_id).include(OrderLine.sku))


async def orders_of_customer(
    session: AsyncSession, customer_id: int
) -> list[Order] | Failure:
    """A customer's orders with each order's lines loaded; `not_found` if the customer does not exist."""
    if await session.first(blog_selectors.user_by_id(customer_id)) is None:
        return Failure("not_found")
    return await session.all(selectors.orders_with_lines_query(customer_id))


async def orders_per_state(
    session: AsyncSession,
) -> list[tuple[OrderState, int, Decimal]]:
    """How many orders and how much money sit in each state. One row per state, one statement."""
    state_col, orders_col, total_col = selectors.per_state_columns()
    return selectors.to_state_totals(
        await session.select(
            selectors.per_state_query(), state_col, orders_col, total_col
        )
    )


async def customer_orders(session: AsyncSession) -> list[CustomerOrders]:
    """Every customer with their order count and what they have spent, typed, in one statement."""
    return await session.annotate(
        selectors.customer_orders_query(),
        CustomerOrders,
        **selectors.customer_orders_aggregates(),
    )


async def place_order(
    session: AsyncSession,
    *,
    reference: str,
    customer_id: int,
    warehouse_id: int,
    lines: Sequence[tuple[int, int]],
) -> Order | Failure:
    """Places an order: validates, prices every line off its SKU, writes it all and commits ONCE.

    The order of the refusals is the same as the synchronous twin's and it is deliberate there: the
    shape first, then the three existence checks, and the uniqueness of the reference LAST, because
    it is the only one another request can turn from false to true while this one is running.
    """
    if not reference or not lines:
        return Failure("missing_fields")
    if any(quantity <= 0 for _, quantity in lines):
        return Failure("missing_fields")
    if len({sku_id for sku_id, _ in lines}) != len(lines):
        return Failure("missing_fields")

    if await session.first(blog_selectors.user_by_id(customer_id)) is None:
        return Failure("not_found")
    if (await session.first(inventory_selectors.warehouse_by_id(warehouse_id))) is None:
        return Failure("not_found")
    priced: list[tuple[int, int, Decimal]] = []
    for sku_id, quantity in lines:
        sku = await session.first(inventory_selectors.sku_by_id(sku_id))
        if sku is None:
            return Failure("not_found")
        priced.append((sku_id, quantity, sku.price))

    if await session.first(selectors.order_by_reference(reference)) is not None:
        return Failure("conflict")

    total = sum((price * quantity for _, quantity, price in priced), Decimal("0"))
    order = await session.add(
        Order(
            reference=reference,
            total=total,
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            invoice_id=None,
            placed_at=SnakeUtc.now(),
        )
    )
    await session.add_all(
        [
            OrderLine(
                order_id=order.id,
                sku_id=sku_id,
                quantity=quantity,
                unit_price=price,
            )
            for sku_id, quantity, price in priced
        ]
    )
    await session.commit()
    return order


async def set_line(
    session: AsyncSession, *, order_id: int, sku_id: int, quantity: int
) -> OrderLine | Failure:
    """States how many units of a SKU an order wants, adding the line if it was not there. UPSERT.

    Zero is `missing_fields` and not a shortcut for deleting the line, and an order that has been
    billed is a `conflict`: its lines are what the invoice was calculated from.
    """
    if quantity <= 0:
        return Failure("missing_fields")
    order = await session.first(selectors.order_by_id(order_id))
    if order is None:
        return Failure("not_found")
    if order.state not in _OPEN_STATES:
        return Failure("conflict")
    sku = await session.first(inventory_selectors.sku_by_id(sku_id))
    if sku is None:
        return Failure("not_found")

    await session.upsert(
        OrderLine(
            order_id=order_id,
            sku_id=sku_id,
            quantity=quantity,
            unit_price=sku.price,
        ),
        on_conflict=[OrderLine.order_id, OrderLine.sku_id],
        update=[OrderLine.quantity, OrderLine.unit_price],
    )
    await _retotal(session, order)
    await session.commit()
    line = await session.first(selectors.line_by_key(order_id, sku_id))
    assert line is not None
    return line


async def remove_line(
    session: AsyncSession, *, order_id: int, sku_id: int
) -> None | Failure:
    """Removes one line from an order and leaves the total derived. `not_found` if the pair is not there."""
    line = await session.first(selectors.line_by_key(order_id, sku_id))
    if line is None:
        return Failure("not_found")
    order = await session.first(selectors.order_by_id(order_id))
    if order is None:
        return Failure("not_found")
    if order.state not in _OPEN_STATES:
        return Failure("conflict")

    await session.delete(line)
    await _retotal(session, order)
    await session.commit()
    return None


async def cancel_order(session: AsyncSession, *, order_id: int) -> Order | Failure:
    """Cancels an open order, giving back whatever it was holding. `conflict` once it has been billed.

    The two open states cancel DIFFERENTLY, which is the whole reason `OrderState` is an enum: from
    `DRAFT` nothing was promised, from `RESERVED` the hold has to be released or the shelf stays full
    while the warehouse starts refusing orders it could fill.
    """
    await _open_stock_transaction(session)
    order = await session.first(selectors.order_by_id(order_id))
    if order is None:
        await session.rollback()
        return Failure("not_found")
    if order.state not in _OPEN_STATES:
        await session.rollback()
        return Failure("conflict")

    if order.state is OrderState.RESERVED:
        lines = await session.all(selectors.lines_of(order_id))
        held = await _stock_by_sku(
            session, warehouse_id=order.warehouse_id, lines=lines
        )
        for line in lines:
            row = held.get(line.sku_id)
            if row is not None:
                await _release_units(session, stock=row, units=line.quantity)
    await _set_state(session, order=order, state=OrderState.CANCELLED)
    await session.commit()
    return order


async def reserve(session: AsyncSession, *, order_id: int) -> Order | Failure:
    """Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK. All of them or none.

    The three decisions its synchronous twin documents at length hold here unchanged, and the middle
    one is the reason this function is worth having twice. The ISOLATION is declared FIRST, before
    any read, and it is `READ_COMMITTED` because that is what makes "wait for the lock, then decide
    against what the winner left behind" the actual behaviour — under `REPEATABLE READ` the second
    customer's locking read does not wait and refuse, it dies with a serialisation failure.

    The LOCK is taken over every line in ONE statement in a fixed order, the DECISION comes before
    any write, and a refusal ROLLS BACK rather than merely returning: it wrote nothing, but it is
    holding row locks, and walking away with them blocks the next customer until the connection goes
    back to the pool.
    """
    await _open_stock_transaction(session)
    order = await session.first(selectors.order_by_id(order_id))
    if order is None:
        await session.rollback()
        return Failure("not_found")
    if order.state is not OrderState.DRAFT:
        await session.rollback()
        return Failure("conflict")

    lines = await session.all(selectors.lines_of(order_id))
    if not lines:
        await session.rollback()
        return Failure("conflict")
    held = await _stock_by_sku(session, warehouse_id=order.warehouse_id, lines=lines)
    for line in lines:
        row = held.get(line.sku_id)
        # A pair with no row holds ZERO, which is a shortage like any other. It is not `not_found`:
        # the order exists, the SKU exists, and what the caller asked is whether there are enough.
        if row is None or row.on_hand - row.reserved < line.quantity:
            await session.rollback()
            return Failure("conflict")

    for line in lines:
        await _hold_units(session, stock=held[line.sku_id], units=line.quantity)
    await _set_state(session, order=order, state=OrderState.RESERVED)
    await session.commit()
    return order


async def settle(
    session: AsyncSession,
    *,
    order_id: int,
    subscription_id: int,
    method: str = "card",
    charge: Charge = accept_every_charge,
) -> Order | Failure:
    """Bills a RESERVED order, takes the money and ships it. FOUR steps, and one of them can say no.

    THE SAVEPOINT, and what is deliberately outside it. Issuing the invoice happens BEFORE the
    savepoint and survives whatever follows, because an issued invoice is a document and not a wish.
    Everything after it is inside — the payment, the shipment, the final state — because those are
    the ones that must not exist if the money did not arrive.

    WHAT A ROLLBACK TO SAVEPOINT DOES NOT UNDO: it rewinds the DATABASE, not the Python objects.
    This ORM has no identity map and no unit of work by design, so the `Stock` instances the shipment
    mutated still carry the shipped numbers after the rewind while the rows behind them are back to
    what they were. The compensation therefore RE-READS the rows, and that is not belt and braces —
    trusting the objects gives no error at all, it commits a `reserved` computed from a state that
    was rolled back.

    And AFTER the rewind the transaction is still alive, which is the whole reason a savepoint is the
    tool and not a `rollback()`. In Postgres a failed statement poisons the transaction, so without
    it the release could not be written at all; and a plain `rollback()` would throw away the invoice
    with it, leaving the units held by an order that is never going to ship.
    """
    await _open_stock_transaction(session)
    order = await session.first(selectors.order_by_id(order_id))
    if order is None:
        await session.rollback()
        return Failure("not_found")
    if order.state is not OrderState.RESERVED:
        await session.rollback()
        return Failure("conflict")
    subscription = await session.first(subscription_by_id(subscription_id))
    if subscription is None:
        await session.rollback()
        return Failure("not_found")
    # Nothing in the schema stops an order pointing at somebody else's invoice, so the rule can only
    # live here. It guards the one query no report recovers from: money added up across two people
    # who never met.
    if subscription.user_id != order.customer_id:
        await session.rollback()
        return Failure("conflict")

    lines = await session.all(selectors.lines_of(order_id))
    held = await _stock_by_sku(session, warehouse_id=order.warehouse_id, lines=lines)
    if any(line.sku_id not in held for line in lines):
        await session.rollback()
        return Failure("conflict")

    invoice = await session.add(
        Invoice(
            amount_cents=_in_cents(order.total),
            subscription_id=subscription_id,
            issued_at=SnakeUtc.now(),
        )
    )
    order.invoice_id = invoice.id
    order.state = OrderState.INVOICED
    await session.update(order)
    try:
        async with session.savepoint():
            await _pay(session, invoice_id=invoice.id, method=method)
            await charge(order.total)
            for line in lines:
                await _ship_held(session, stock=held[line.sku_id], units=line.quantity)
            await _set_state(session, order=order, state=OrderState.SETTLED)
    except PaymentDeclined:
        # The rewind took the payment, the shipment and the state with it. The invoice stayed, and so
        # did the transaction, which is what lets the release be written at all. The rows are read
        # AGAIN because the instances above are stale in the one direction that does not raise.
        fresh = await _stock_by_sku(
            session, warehouse_id=order.warehouse_id, lines=lines
        )
        for line in lines:
            await _release_units(session, stock=fresh[line.sku_id], units=line.quantity)
        await session.commit()
        return Failure("payment_declined")
    await session.commit()
    return order


async def _pay(session: AsyncSession, *, invoice_id: int, method: str) -> None:
    """Records the payment and marks the invoice paid, BEFORE the processor answers.

    That order is deliberate and the savepoint is what makes it safe: charging first and recording
    after has a window in which the money has been taken and nothing in the database says so, and no
    rollback fixes that one.
    """
    invoice = await session.first(invoice_by_id(invoice_id))
    if invoice is None:
        return
    kind = PAYMENT_KINDS.get(method)
    if kind is None:
        return
    await session.add(
        kind(
            amount_cents=invoice.amount_cents,
            invoice_id=invoice_id,
            paid_at=SnakeUtc.now(),
        )
    )
    invoice.paid = True
    await session.update(invoice)


async def attach_invoice(
    session: AsyncSession, *, order_id: int, invoice_id: int
) -> Order | Failure:
    """Bills an open order against an EXISTING invoice and moves it to `INVOICED`.

    The plain half of the joint with `billing`: it links the two rows and stops. `settle` above is
    the half that can fail in the middle, which is why that one needs a savepoint and this one does
    not. The invoice is looked up rather than trusted, so a stale id from a form is a `not_found`
    here instead of a foreign key violation raised inside the commit.
    """
    order = await session.first(selectors.order_by_id(order_id))
    if order is None:
        return Failure("not_found")
    if order.state not in _OPEN_STATES:
        return Failure("conflict")
    if await session.first(invoice_by_id(invoice_id)) is None:
        return Failure("not_found")
    order.invoice_id = invoice_id
    order.state = OrderState.INVOICED
    await session.update(order)
    await session.commit()
    return order


async def remove_order(session: AsyncSession, *, order_id: int) -> None | Failure:
    """Deletes an order. `not_found` if it is not there, `conflict` if its lines would be orphaned.

    The engine would refuse anyway, with a driver error from inside a commit. Checking first turns
    that into something a delete page can explain: an order that has lines gets cancelled, not
    deleted.
    """
    order = await session.first(selectors.order_by_id(order_id))
    if order is None:
        return Failure("not_found")
    if await session.count(selectors.lines_count_query(order_id)) > 0:
        return Failure("conflict")
    await session.delete(order)
    await session.commit()
    return None


async def order_report(
    session: AsyncSession,
    *,
    minimum_orders: int = 2,
    sequence_size: int = 20,
    highlight_size: int = 5,
) -> OrderReport:
    """The whole orders report. SIX statements on Postgres and MySQL, SEVEN on SQLite.

    The difference is `highlights`, and it is declared rather than hidden: the compound needs
    parentheses to keep a `LIMIT` inside a branch and SQLite refuses them, so there it falls back to
    two statements folded in Python. Both paths go through the same fragments the synchronous twin
    uses, which is what stops the two demos from showing different lists on the one engine that
    already takes the slower route.
    """
    name_col, placed_col, spent_col = selectors.repeat_customers_columns()
    reference_col, username_col, at_col, position_col = (
        selectors.order_sequence_columns()
    )
    state_col, orders_col, total_col = selectors.per_state_columns()
    return OrderReport(
        customers=await customer_orders(session),
        repeat_customers=selectors.to_customer_totals(
            await session.select(
                selectors.repeat_customers_query(minimum_orders=minimum_orders),
                name_col,
                placed_col,
                spent_col,
            )
        ),
        states=selectors.to_state_totals(
            await session.select(
                selectors.per_state_query(), state_col, orders_col, total_col
            )
        ),
        sequence=selectors.to_order_sequence(
            await session.select(
                selectors.order_sequence_query(limit=sequence_size),
                reference_col,
                username_col,
                at_col,
                position_col,
            )
        ),
        highlights=await _highlights(session, size=highlight_size),
        baskets=[
            (reference, int(lines), skus or "")
            for reference, lines, skus in await session.select(
                selectors.baskets_query(), *selectors.baskets_columns()
            )
        ],
    )


async def _highlights(session: AsyncSession, *, size: int) -> list[Order]:
    """The biggest and the newest orders as ONE deduplicated list, by whichever route the engine has."""
    if session.dialect.supports_parenthesised_compound:
        return await session.all(selectors.highlights_compound(size))
    biggest, newest = selectors.highlight_branches(size)
    return selectors.fold_highlights(
        await session.all(newest), await session.all(biggest)
    )


async def stream_order_lines(
    session: AsyncSession, *, state: OrderState | None = None
) -> AsyncIterator[OrderLine]:
    """The order lines as a STREAM, for the export.

    `async def` for the net, not for an `await` this body needs: `AsyncSession.iterate()` hands back
    the async iterator immediately, exactly as the synchronous `iterate()` hands back a plain one.
    See `inventory_usecases.stream_movements` for why the signature is still a coroutine and what
    that costs the caller.
    """
    return session.iterate(
        selectors.lines_to_export(state), chunk=selectors.EXPORT_CHUNK
    )
