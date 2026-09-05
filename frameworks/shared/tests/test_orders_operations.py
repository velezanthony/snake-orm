"""The two operations the `orders` domain exists for, pinned where a laptop can run them.

`reserve` and `settle` are the reason there is a ninth domain at all: they are the only writes in
these demos that read across three domains, decide something, and can go wrong halfway. What this
file owns is their DOMAIN behaviour — which states they accept, what they hold, what they give back
— and it runs on the in-memory SQLite of `conftest.py`, so it costs nothing and runs anywhere.

What it deliberately does NOT own is the half that needs two connections and a real engine: that the
lock is a lock, and that the savepoint rewinds the billing without killing the transaction. SQLite
answers `Nope` to row locking and its writers are exclusive at the FILE, so a race here would be
green whether or not `reserve` ever asked for a row. That half lives in `test_orders_concurrency.py`
against a real Postgres, and it is the phase's gate.

Both halves matter and neither replaces the other. Without this file the operations would only be
tested where a server is up; without the other one the lock would be decoration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta, timezone
from decimal import Decimal

from snakeorm import SnakeUtc, SnakeQuery, SnakeSession

from shared.models import (
    Invoice,
    MovementReason,
    OrderState,
    Payment,
    Plan,
    SkuKind,
    Stock,
    StockMovement,
    Subscription,
    User,
)
from shared.usecases import inventory_usecases as inventory
from shared.usecases import orders_usecases as usecases
from shared.usecases.result import Failure


@dataclass(frozen=True, slots=True)
class Scene:
    """Everything one operation needs, already in the database: who buys, from where, and what.

    It travels as one value because the operations need all five ids together and a test that
    rebuilt them one call at a time would spend more lines on the fixture than on the assertion.
    """

    warehouse_id: int
    sku_id: int
    customer_id: int
    order_id: int
    subscription_id: int


def _scene(
    session: SnakeSession,
    *,
    on_hand: int,
    wanted: int,
    held: int = 0,
    price: str = "10.00",
    tag: str = "one",
) -> Scene:
    """One customer, one warehouse holding `on_hand` units of one SKU, and a DRAFT order for `wanted`.

    It is built through the USE CASES of the other two domains and not with raw inserts. The point of
    this domain is that it is the joint, so a fixture that wrote its own stock row would be testing a
    copy of the inventory rather than the inventory — and the day `count_stock` changes what it
    writes, this file would keep passing over a shape nobody else produces.
    """
    user = session.add(
        User(username=f"buyer-{tag}", email=f"buyer-{tag}@demo.dev", password_hash="x")
    )
    plan = session.add(Plan(name=f"plan-{tag}", price_cents=900))
    session.commit()
    subscription = session.add(
        Subscription(user_id=user.id, plan_id=plan.id, started_at=SnakeUtc.now())
    )
    session.commit()

    warehouse = inventory.create_warehouse(
        session,
        code=tag[:3].upper(),
        name=f"Warehouse {tag}",
        opened_on=date(2020, 3, 14),
        shift_start=time(6, 30),
        cutoff=time(18, 0, tzinfo=timezone(timedelta(hours=1))),
    )
    assert not isinstance(warehouse, Failure), warehouse
    sku = inventory.create_sku(
        session,
        name=f"Widget {tag}",
        kind=SkuKind.PHYSICAL,
        price=Decimal(price),
        weight_kg=1.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(sku, Failure), sku
    counted = inventory.count_stock(
        session, warehouse_id=warehouse.id, sku_id=sku.id, on_hand=on_hand
    )
    assert not isinstance(counted, Failure), counted
    if held:
        levels = inventory.update_stock(
            session,
            warehouse_id=warehouse.id,
            sku_id=sku.id,
            on_hand=on_hand,
            reserved=held,
        )
        assert not isinstance(levels, Failure), levels

    order = usecases.place_order(
        session,
        reference=f"ORD-{tag}",
        customer_id=user.id,
        warehouse_id=warehouse.id,
        lines=[(sku.id, wanted)],
    )
    assert not isinstance(order, Failure), order
    return Scene(
        warehouse_id=warehouse.id,
        sku_id=sku.id,
        customer_id=user.id,
        order_id=order.id,
        subscription_id=subscription.id,
    )


def _levels(session: SnakeSession, scene: Scene) -> tuple[int, int]:
    """What the stock row holds right now, as `(quantity, reserved)`. Zero if the pair is gone."""
    row = session.first(
        SnakeQuery(Stock).filter(
            Stock.warehouse_id == scene.warehouse_id, Stock.sku_id == scene.sku_id
        )
    )
    return (0, 0) if row is None else (row.on_hand, row.reserved)


def _state(session: SnakeSession, order_id: int) -> OrderState:
    """The order's state, unwrapped, so the assertion that follows reads as one line."""
    order = usecases.get_order(session, order_id)
    assert not isinstance(order, Failure), order
    return order.state


# --- reserve -------------------------------------------------------------------------------------


def test_reserving_holds_the_units_without_taking_them_off_the_shelf(
    session: SnakeSession,
) -> None:
    """A reservation raises `reserved` and leaves `quantity` alone: the units are promised, not gone.

    The two columns say different things and this is the operation that proves it. `quantity` is what
    is physically there and only a movement changes it; `reserved` is what is already promised to
    somebody. A reservation that decremented `quantity` would make the warehouse's own count wrong
    the moment somebody walked in and looked at the shelf.
    """
    scene = _scene(session, on_hand=10, wanted=3)

    reserved = usecases.reserve(session, order_id=scene.order_id)

    assert not isinstance(reserved, Failure), reserved
    assert reserved.state is OrderState.RESERVED
    assert _levels(session, scene) == (10, 3)


def test_a_reservation_counts_what_is_already_promised_and_not_only_the_shelf(
    session: SnakeSession,
) -> None:
    """Availability is `quantity - reserved`. Ten on the shelf with nine promised leaves one.

    Reading `quantity` alone is the bug this column pair exists to prevent: it would let the same ten
    units be promised to four different customers, and every one of them would be told yes.
    """
    scene = _scene(session, on_hand=10, held=9, wanted=3)

    refused = usecases.reserve(session, order_id=scene.order_id)

    assert refused == Failure("conflict")
    assert _levels(session, scene) == (10, 9)


def test_a_reservation_that_cannot_be_filled_whole_holds_nothing_at_all(
    session: SnakeSession,
) -> None:
    """All or nothing: one short line refuses the WHOLE order, and the other lines stay free.

    A partial reservation is not a state this domain has. Holding what it could and telling the
    customer to come back for the rest would leave units promised to an order that will never ship,
    and nothing in the model can tell those apart from a reservation that is going to be settled.
    """
    scene = _scene(session, on_hand=10, wanted=2, tag="two")
    scarce = inventory.create_sku(
        session,
        name="Scarce",
        kind=SkuKind.PHYSICAL,
        price=Decimal("5.00"),
        weight_kg=1.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(scarce, Failure), scarce
    inventory.count_stock(
        session, warehouse_id=scene.warehouse_id, sku_id=scarce.id, on_hand=1
    )
    added = usecases.set_line(
        session, order_id=scene.order_id, sku_id=scarce.id, quantity=4
    )
    assert not isinstance(added, Failure), added

    refused = usecases.reserve(session, order_id=scene.order_id)

    assert refused == Failure("conflict")
    assert _levels(session, scene) == (10, 0)
    scarce_row = session.first(
        SnakeQuery(Stock).filter(
            Stock.warehouse_id == scene.warehouse_id, Stock.sku_id == scarce.id
        )
    )
    assert scarce_row is not None and scarce_row.reserved == 0


def test_a_sku_the_warehouse_never_stocked_is_a_refusal_and_not_a_crash(
    session: SnakeSession,
) -> None:
    """A missing stock row means ZERO units, which is a refusal like any other shortage.

    The pair `(warehouse, sku)` is `Stock`'s identity, so "this warehouse has never held this SKU"
    and "this warehouse has none left" are the same answer to the only question a reservation asks.
    Treating the missing row as `not_found` would answer 404 to an order that exists perfectly well.
    """
    scene = _scene(session, on_hand=10, wanted=1, tag="three")
    unstocked = inventory.create_sku(
        session,
        name="Never held",
        kind=SkuKind.PHYSICAL,
        price=Decimal("1.00"),
        weight_kg=1.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(unstocked, Failure), unstocked
    usecases.set_line(session, order_id=scene.order_id, sku_id=unstocked.id, quantity=1)

    refused = usecases.reserve(session, order_id=scene.order_id)

    assert refused == Failure("conflict")
    assert _levels(session, scene) == (10, 0)


def test_only_a_draft_can_be_reserved_so_reserving_twice_is_refused(
    session: SnakeSession,
) -> None:
    """Reserving an order that is already RESERVED would hold the units a second time.

    This is the guard that makes a retried request safe. A form submitted twice, or a browser that
    replays a POST, would otherwise promise four units to an order that asked for two — and nothing
    downstream would ever notice, because both halves of the arithmetic look right on their own.
    """
    scene = _scene(session, on_hand=10, wanted=2)
    first = usecases.reserve(session, order_id=scene.order_id)
    assert not isinstance(first, Failure), first

    again = usecases.reserve(session, order_id=scene.order_id)

    assert again == Failure("conflict")
    assert _levels(session, scene) == (10, 2)


def test_reserving_an_order_that_is_not_there_says_so(session: SnakeSession) -> None:
    """An id that came from a URL is whatever somebody typed: 404, not a stack trace."""
    assert usecases.reserve(session, order_id=9999) == Failure("not_found")


# --- settle --------------------------------------------------------------------------------------


def test_settling_takes_the_units_off_the_shelf_and_off_the_hold(
    session: SnakeSession,
) -> None:
    """The happy path in one assertion: the promise becomes a shipment, and both columns drop.

    `quantity` falls because the units left the building and `reserved` falls because they are no
    longer merely promised. Dropping only one of the two is the classic half-shipment: either the
    warehouse count stays high forever, or the same units get promised again tomorrow.
    """
    scene = _scene(session, on_hand=10, wanted=3)
    assert not isinstance(usecases.reserve(session, order_id=scene.order_id), Failure)

    settled = usecases.settle(
        session, order_id=scene.order_id, subscription_id=scene.subscription_id
    )

    assert not isinstance(settled, Failure), settled
    assert settled.state is OrderState.SETTLED
    assert _levels(session, scene) == (7, 0)


def test_settling_leaves_the_invoice_paid_and_the_order_pointing_at_it(
    session: SnakeSession,
) -> None:
    """The joint with `billing`, written rather than declared: an invoice, a payment and the link.

    The order's `invoice_id` is what turns two domains into one graph. Without it the money and the
    goods are two histories that happen to have the same dates on them.
    """
    scene = _scene(session, on_hand=10, wanted=2)
    assert not isinstance(usecases.reserve(session, order_id=scene.order_id), Failure)

    settled = usecases.settle(
        session, order_id=scene.order_id, subscription_id=scene.subscription_id
    )

    assert not isinstance(settled, Failure), settled
    assert settled.invoice_id is not None
    invoice = session.first(
        SnakeQuery(Invoice).filter(Invoice.id == settled.invoice_id)
    )
    assert invoice is not None
    assert invoice.paid is True
    # The order's money is a NUMERIC and billing's is an integer number of cents: 2 x 10.00 = 2000.
    assert invoice.amount_cents == 2000
    payments = session.all(
        SnakeQuery(Payment).filter(Payment.invoice_id == settled.invoice_id)
    )
    assert [payment.amount_cents for payment in payments] == [2000]


def test_settling_records_why_the_stock_moved(session: SnakeSession) -> None:
    """A shipment writes its movement: stock that changed with nothing behind it is unexplainable.

    It is the same rule `inventory` holds for `receive` and `ship`, and it has to hold here too or
    the audit trail would have a hole exactly where the money is.
    """
    scene = _scene(session, on_hand=10, wanted=4)
    assert not isinstance(usecases.reserve(session, order_id=scene.order_id), Failure)

    assert not isinstance(
        usecases.settle(
            session, order_id=scene.order_id, subscription_id=scene.subscription_id
        ),
        Failure,
    )

    movements = session.all(
        SnakeQuery(StockMovement).filter(
            StockMovement.stock_warehouse_id == scene.warehouse_id,
            StockMovement.stock_sku_id == scene.sku_id,
            StockMovement.reason == MovementReason.SALE,
        )
    )
    assert [movement.delta for movement in movements] == [-4]


def test_only_a_reserved_order_can_be_settled(session: SnakeSession) -> None:
    """Settling a DRAFT would ship units nobody ever held: the reservation IS the promise.

    Without the guard, `settle` would decrement a `reserved` that was never raised and drive it
    negative — which the engine's CHECK would catch, as a driver error, from inside a commit.
    """
    scene = _scene(session, on_hand=10, wanted=2)

    refused = usecases.settle(
        session, order_id=scene.order_id, subscription_id=scene.subscription_id
    )

    assert refused == Failure("conflict")
    assert _levels(session, scene) == (10, 0)


def test_the_invoice_must_bill_the_customer_who_placed_the_order(
    session: SnakeSession,
) -> None:
    """A subscription belonging to somebody else is refused: it would bill the wrong person.

    Nothing in the schema stops it — `Order.invoice_id` does not know whose subscription the invoice
    hangs off — so this rule can only live in the operation. The seeder says the same thing from the
    other side, and both are guarding the one query a report cannot recover from: money added up
    across two people who never met.
    """
    scene = _scene(session, on_hand=10, wanted=2, tag="four")
    stranger = _scene(session, on_hand=1, wanted=1, tag="five")
    assert not isinstance(usecases.reserve(session, order_id=scene.order_id), Failure)

    refused = usecases.settle(
        session, order_id=scene.order_id, subscription_id=stranger.subscription_id
    )

    assert refused == Failure("conflict")
    assert _state(session, scene.order_id) is OrderState.RESERVED
    assert _levels(session, scene) == (10, 2)


def test_settling_against_a_subscription_that_is_not_there_says_so(
    session: SnakeSession,
) -> None:
    """A stale subscription id is a 404 here, not a foreign key violation raised inside a commit."""
    scene = _scene(session, on_hand=10, wanted=1)
    assert not isinstance(usecases.reserve(session, order_id=scene.order_id), Failure)

    assert usecases.settle(
        session, order_id=scene.order_id, subscription_id=9999
    ) == Failure("not_found")


# --- cancel --------------------------------------------------------------------------------------


def test_cancelling_a_draft_gives_nothing_back_because_nothing_was_held(
    session: SnakeSession,
) -> None:
    """From DRAFT there is no hold to release, and releasing one anyway would invent units.

    This is the difference `OrderState` exists to carry. A boolean `cancelled` could not tell the two
    cancellations apart, and the one that guessed wrong would raise the warehouse's availability by
    units nobody ever promised.
    """
    scene = _scene(session, on_hand=10, wanted=3)

    cancelled = usecases.cancel_order(session, order_id=scene.order_id)

    assert not isinstance(cancelled, Failure), cancelled
    assert cancelled.state is OrderState.CANCELLED
    assert _levels(session, scene) == (10, 0)


def test_cancelling_a_reservation_gives_the_units_back(session: SnakeSession) -> None:
    """From RESERVED the hold is released: the units go back to being available to everybody else.

    A cancellation that left `reserved` up is how a warehouse ends up saying it has nothing while
    the shelf is full — and it is invisible, because `quantity` is right the whole time.
    """
    scene = _scene(session, on_hand=10, wanted=3)
    assert not isinstance(usecases.reserve(session, order_id=scene.order_id), Failure)
    assert _levels(session, scene) == (10, 3)

    cancelled = usecases.cancel_order(session, order_id=scene.order_id)

    assert not isinstance(cancelled, Failure), cancelled
    assert cancelled.state is OrderState.CANCELLED
    assert _levels(session, scene) == (10, 0)


def test_cancelling_a_settled_order_is_a_refund_and_not_a_cancellation(
    session: SnakeSession,
) -> None:
    """Once the money and the goods have moved, `cancel` refuses: undoing them is another operation.

    A refund puts money back and a return puts units back, and neither is what this does. Answering
    `conflict` is the operation saying it is the wrong tool, which is the only thing it can honestly
    say about a state it was not written for.
    """
    scene = _scene(session, on_hand=10, wanted=2)
    assert not isinstance(usecases.reserve(session, order_id=scene.order_id), Failure)
    assert not isinstance(
        usecases.settle(
            session, order_id=scene.order_id, subscription_id=scene.subscription_id
        ),
        Failure,
    )

    refused = usecases.cancel_order(session, order_id=scene.order_id)

    assert refused == Failure("conflict")
    assert _state(session, scene.order_id) is OrderState.SETTLED
    assert _levels(session, scene) == (8, 0)
