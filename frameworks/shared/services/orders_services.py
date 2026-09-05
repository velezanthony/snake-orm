"""orders domain — SERVICES: writes over the orders and their lines.

Every framework re-exports them from `apps/orders/services.py`.

Services do NOT commit. That is the use case's call, because the use case is the one that knows
whether the operation is finished — and in this domain "finished" is the whole question: an order
whose lines landed and whose total did not is a row that adds up to a lie, and there is no state in
between where stopping would be correct.

`set_line` is the write that earns the module. It is an UPSERT over a COMPOSITE conflict target, the
second one in the repo after the inventory's: wanting more of a SKU that is already on the order is
the SAME line with a bigger number, and doing it as read-then-branch is a race with two requests
editing one order. The pair being the conflict target is what makes the duplicate impossible rather
than unlikely.

`retotal` exists because `Order.total` is DERIVED and stored, so every write that touches a line has
to leave it derived. It takes the lines it was given instead of re-reading them: the caller has just
written them, and re-reading would both cost a statement and read a state that another writer may
have moved underneath.
"""

from __future__ import annotations

from decimal import Decimal
from collections.abc import Sequence

from snakeorm import SnakeUtc, SnakeSession

from shared.models import Order, OrderLine, OrderState


def create_order(
    session: SnakeSession,
    *,
    reference: str,
    customer_id: int,
    warehouse_id: int,
    total: Decimal,
) -> Order:
    """Creates an order in `DRAFT` with a total the caller has already computed.

    The total is a parameter and not something worked out in here, because the lines it comes from
    are the caller's: this writes ONE row and knows nothing about what is about to hang off it.

    `placed_at` is set to now rather than left to a server default: the seeder spreads it over the
    history to give the report something to show, and a column cannot be both.
    """
    return session.add(
        Order(
            reference=reference,
            total=total,
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            invoice_id=None,
            placed_at=SnakeUtc.now(),
        )
    )


def set_line(
    session: SnakeSession,
    *,
    order_id: int,
    sku_id: int,
    quantity: int,
    unit_price: Decimal,
) -> None:
    """States that an order wants `quantity` of a SKU, whether or not the line existed. UPSERT.

    The conflict target is BOTH columns, because the pair is the identity. Reading first and then
    choosing between insert and update is the same operation with a window in the middle, and two
    requests adding the same SKU to one order land inside that window.

    It SETS rather than adds, and the two are different operations: "the order wants five of these"
    is idempotent and survives a retried request, while "add five more" applied twice quietly doubles
    what the customer asked for. The caller that means the second one does the arithmetic and says so.

    `unit_price` is written on every upsert on purpose: the line records the price agreed at the
    moment of ordering, so a line whose quantity is being changed today is being re-agreed today.
    """
    session.upsert(
        OrderLine(
            order_id=order_id,
            sku_id=sku_id,
            quantity=quantity,
            unit_price=unit_price,
        ),
        on_conflict=[OrderLine.order_id, OrderLine.sku_id],
        update=[OrderLine.quantity, OrderLine.unit_price],
    )


def add_lines(session: SnakeSession, lines: Sequence[OrderLine]) -> None:
    """Inserts an order's lines in one go: a batch, sliced by the engine's placeholder ceiling.

    It is the CREATION path, where the lines are known to be new, so there is nothing to conflict
    with and a plain multi-row insert is both correct and one statement. `set_line` is the edit path
    and pays for the upsert because there it is not known.
    """
    if lines:
        session.add_all(list(lines))


def delete_line(session: SnakeSession, line: OrderLine) -> None:
    """Deletes one line by its composite key. Nothing hangs off a line, so nothing is orphaned."""
    session.delete(line)


def retotal(
    session: SnakeSession, *, order: Order, lines: Sequence[OrderLine]
) -> Order:
    """Recomputes the order's total from the lines it was handed, and writes it.

    The arithmetic is in `Decimal`, never in `float`: money that is summed as binary floating point
    comes out a cent short often enough to be noticed and rarely enough not to be reproducible.
    The seed of the sum is `Decimal("0")` for the same reason — starting from the integer `0` makes
    the first addition decide the type, and an empty order would total `int`.
    """
    order.total = sum((line.unit_price * line.quantity for line in lines), Decimal("0"))
    session.update(order)
    return order


def set_state(session: SnakeSession, *, order: Order, state: OrderState) -> Order:
    """Moves an order to another state. WHICH moves are legal is the use case's rule, not this one.

    Deliberately dumb: a service that also decided the transitions would be the only place the rule
    lived, and the rule needs to be where the caller can be told WHY the move was refused.
    """
    order.state = state
    session.update(order)
    return order


def attach_invoice(session: SnakeSession, *, order: Order, invoice_id: int) -> Order:
    """Points a settled-to-be order at the invoice that bills it, and marks it `INVOICED`.

    The two writes are one unit of work, and they have to be: an order pointing at an invoice while
    still saying `DRAFT`, or saying `INVOICED` while pointing at nothing, are both states no reader
    can interpret. The caller commits once and both land or neither does.
    """
    order.invoice_id = invoice_id
    order.state = OrderState.INVOICED
    session.update(order)
    return order


def delete_order(session: SnakeSession, order: Order) -> None:
    """Deletes an order.

    It only works on an order with NO lines, and that is the engine holding the line rather than a
    gap here: the lines are what the order WAS, and a foreign key that let them be orphaned — or
    cascaded away — would turn "remove this row" into "erase what the customer asked for". An order
    that has lines gets cancelled, not deleted.
    """
    session.delete(order)
