"""The half of the `orders` operations that only a REAL Postgres and TWO connections can prove.

Everything here is unprovable on the SQLite the rest of this suite runs on, and unprovable in the
interesting direction: it would go GREEN. SQLite answers `Nope` to row locking, so a reservation
there locks nothing and two customers taking the last unit one after the other look exactly like two
customers taking it correctly. A green run on the wrong engine is worse than a red one, because
somebody reads it.

So these tests do three things nothing else in `frameworks/` does:

- they hold a row lock on ONE connection and watch the other one WAIT for it, which is the only way
  to show that `reserve` takes a lock rather than merely calling a method named after one;
- they make the billing step of `settle` fail and check what survives, which is what a savepoint is
  for and cannot be seen where a rollback would have been enough;
- they pin the ISOLATION LEVEL by showing what the operation does at the other one — a measurement,
  not an opinion, and the reason `set_isolation` is called at all.

Without a server they skip, with the repository's phrase, and `SNAKEORM_REQUIRE_POSTGRES=true` turns
that skip into a failure. See `conftest.py`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, time, timedelta, timezone
from decimal import Decimal

import pytest
from snakeorm import (
    AsyncSession,
    PostgresDialect,
    SnakeIsolation,
    SnakeQuery,
    SnakeSession,
    SnakeUtc,
)
from snakeorm.drivers import AsyncPsycopgDriver, SnakeDriver

from shared import aio

from shared.models import (
    Invoice,
    MovementReason,
    Order,
    OrderState,
    Payment,
    Plan,
    SkuKind,
    Stock,
    StockMovement,
    Subscription,
    User,
)
from shared.selectors import inventory_selectors
from shared.usecases import inventory_usecases as inventory
from shared.usecases import orders_usecases as usecases
from shared.usecases.result import Failure

# How long a blocked statement is given before the test gives up on it. It is not a timing
# assertion: the point is that a WAIT ends, not that it ends quickly. Long enough that a loaded
# laptop does not report a lock where there is none, short enough that a hang is not a coffee break.
_PATIENCE = "1500ms"


@dataclass(frozen=True, slots=True)
class Contest:
    """One unit on a shelf and two orders that both want it. The whole point of the domain, as data."""

    warehouse_id: int
    sku_id: int
    first_order: int
    second_order: int
    first_subscription: int


def _contest(session: SnakeSession, *, on_hand: int = 1, wanted: int = 1) -> Contest:
    """Builds the contest through the USE CASES of the other domains, never with raw inserts.

    Building it by hand would make this file's setup a second, private copy of what `inventory` and
    `billing` write — and the day either of them changes shape, the race would keep passing over data
    nothing else in the repository produces.
    """
    buyer = session.add(
        User(username="buyer-a", email="buyer-a@demo.dev", password_hash="x")
    )
    rival = session.add(
        User(username="buyer-b", email="buyer-b@demo.dev", password_hash="x")
    )
    plan = session.add(Plan(name="plan-race", price_cents=900))
    session.commit()
    subscription = session.add(
        Subscription(user_id=buyer.id, plan_id=plan.id, started_at=SnakeUtc.now())
    )
    session.commit()

    warehouse = inventory.create_warehouse(
        session,
        code="MAD",
        name="Warehouse Madrid",
        opened_on=date(2020, 3, 14),
        shift_start=time(6, 30),
        cutoff=time(18, 0, tzinfo=timezone(timedelta(hours=1))),
    )
    assert not isinstance(warehouse, Failure), warehouse
    sku = inventory.create_sku(
        session,
        name="The last one",
        kind=SkuKind.PHYSICAL,
        price=Decimal("10.00"),
        weight_kg=1.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(sku, Failure), sku
    counted = inventory.count_stock(
        session, warehouse_id=warehouse.id, sku_id=sku.id, on_hand=on_hand
    )
    assert not isinstance(counted, Failure), counted

    orders: list[int] = []
    for index, customer in enumerate((buyer, rival)):
        order = usecases.place_order(
            session,
            reference=f"ORD-RACE-{index}",
            customer_id=customer.id,
            warehouse_id=warehouse.id,
            lines=[(sku.id, wanted)],
        )
        assert not isinstance(order, Failure), order
        orders.append(order.id)
    return Contest(
        warehouse_id=warehouse.id,
        sku_id=sku.id,
        first_order=orders[0],
        second_order=orders[1],
        first_subscription=subscription.id,
    )


def _levels(session: SnakeSession, contest: Contest) -> tuple[int, int]:
    """What the stock row holds right now, as `(quantity, reserved)`, read on the given connection."""
    row = session.first(
        SnakeQuery(Stock).filter(
            Stock.warehouse_id == contest.warehouse_id, Stock.sku_id == contest.sku_id
        )
    )
    assert row is not None
    return (row.on_hand, row.reserved)


# --- the lock ------------------------------------------------------------------------------------


def test_a_reservation_waits_for_the_row_the_other_customer_is_holding(
    postgres_pair: tuple[SnakeSession, SnakeSession],
    postgres_drivers: tuple[SnakeDriver, SnakeDriver],
) -> None:
    """THE GATE OF THIS PHASE: `reserve` BLOCKS on a stock row somebody else has locked.

    The second session is stopped exactly where `reserve` stops in the middle of its work — holding
    the rows, not yet committed — and then the first one is asked to reserve the same SKU. It has to
    wait, and it is given a `statement_timeout` so that "it waited" is something a test can observe
    instead of something it hangs on.

    WHAT HAPPENS WITH THE LOCK REMOVED, checked by removing it: take `.for_update()` out of
    `inventory_selectors.lock_stock` and nothing raises here at all — `DID NOT RAISE QueryCanceled`.
    The first session does not wait. It reads the row the rival is in the middle of taking, finds the
    single unit still free, promises it and answers `RESERVED`. Both customers have then been told
    yes about one unit — and it gets worse than a wrong number, because a `Stock` write carries an
    ABSOLUTE value and not a delta: whichever of the two commits last overwrites the other's hold, so
    the row still reads `reserved = 1` and nothing anywhere records that it was promised twice. There
    is no error, no impossible number and no trace. That is the bug this whole domain exists to make
    visible, and this test is red exactly when it is present.
    """
    import psycopg2

    buyer, rival = postgres_pair
    driver_buyer, _ = postgres_drivers
    contest = _contest(buyer)
    # The instrument is the TEST's, on the test's own connection: the operation knows nothing about
    # it. `SET` without `LOCAL` outlives the commit, which is why it is set once and committed here —
    # `reserve` opens with `SET TRANSACTION` and would refuse a connection with work in flight.
    driver_buyer.execute(f"SET statement_timeout = '{_PATIENCE}'", ())
    driver_buyer.commit()

    # The rival is now exactly where `reserve` is between taking its rows and deciding: the lock
    # held, nothing written, nothing committed. Taken with the very selector the operation uses, so
    # this is that moment and not an impression of it — and it holds ONLY the read lock, which is the
    # one under test. Writing the hold too would block the other session on the row's WRITE lock
    # instead, and the test would pass with `for_update` removed: green for the wrong reason.
    inventory_selectors.lock_stock(
        rival, warehouse_id=contest.warehouse_id, sku_ids=[contest.sku_id]
    )

    with pytest.raises(psycopg2.errors.QueryCanceled):
        usecases.reserve(buyer, order_id=contest.first_order)

    buyer.rollback()
    rival.rollback()


def test_two_customers_cannot_both_be_promised_the_last_unit(
    postgres_pair: tuple[SnakeSession, SnakeSession],
) -> None:
    """The outcome the lock buys: the loser is REFUSED, cleanly, and the unit is promised once.

    This is the same race resolved rather than caught in the act. The winner commits its hold; the
    loser's locking read waits for that commit, sees the unit it wanted already spoken for, and
    answers `conflict` — a refusal a page can explain, not a driver error and not a second promise.

    Note what the loser is deciding against: `quantity` never moved. Availability is
    `quantity - reserved`, so the whole disagreement lives in a column the shelf knows nothing about.
    """
    winner, loser = postgres_pair
    contest = _contest(winner)

    reserved = usecases.reserve(winner, order_id=contest.first_order)
    refused = usecases.reserve(loser, order_id=contest.second_order)

    assert not isinstance(reserved, Failure), reserved
    assert reserved.state is OrderState.RESERVED
    assert refused == Failure("conflict")
    assert _levels(loser, contest) == (1, 1)


def test_the_refused_reservation_lets_go_of_the_rows_it_locked(
    postgres_pair: tuple[SnakeSession, SnakeSession],
    postgres_drivers: tuple[SnakeDriver, SnakeDriver],
) -> None:
    """A refusal ends its transaction: it wrote nothing, but it was HOLDING the rows.

    The failure this guards against has no symptom at the scene. A `reserve` that returned `conflict`
    while still holding the locks leaves them held until the connection goes back to the pool, and
    what breaks is the NEXT customer, on another request, with a hang whose cause is three layers
    away. Here the second session takes the same rows immediately afterwards, under a timeout, and
    the timeout not firing is the whole assertion.
    """
    loser, other = postgres_pair
    _, driver_other = postgres_drivers
    contest = _contest(loser, on_hand=0)
    driver_other.execute(f"SET statement_timeout = '{_PATIENCE}'", ())
    driver_other.commit()

    assert usecases.reserve(loser, order_id=contest.first_order) == Failure("conflict")

    locked = inventory_selectors.lock_stock(
        other, warehouse_id=contest.warehouse_id, sku_ids=[contest.sku_id]
    )
    assert [row.sku_id for row in locked] == [contest.sku_id]
    other.rollback()


def test_repeatable_read_would_kill_the_loser_instead_of_letting_it_refuse(
    postgres_pair: tuple[SnakeSession, SnakeSession],
) -> None:
    """WHY `reserve` declares READ COMMITTED, measured rather than asserted in a comment.

    The same race, run by hand at the other isolation level. Under `REPEATABLE READ` the loser's
    locking read does not wait and then decide against the new number: Postgres refuses to serialise
    it and raises `could not serialize access due to concurrent update`. The customer would get a
    driver error where the operation means to answer `conflict`.

    So the level is load-bearing, and it is not something to take on trust from the engine. It is
    Postgres's default, but `default_transaction_isolation` is a server setting that can move it, and
    MySQL — which these demos also run on — defaults to `REPEATABLE READ`. This test is what stops
    the `set_isolation` call in `_open_stock_transaction` from looking like decoration to whoever
    reads it next.
    """
    import psycopg2

    winner, loser = postgres_pair
    contest = _contest(winner)
    query = SnakeQuery(Stock).filter(
        Stock.warehouse_id == contest.warehouse_id, Stock.sku_id == contest.sku_id
    )

    loser.set_isolation(SnakeIsolation.REPEATABLE_READ)
    loser.all(query)  # the snapshot opens here, before the winner writes

    winner.set_isolation(SnakeIsolation.READ_COMMITTED)
    row = winner.all(query.for_update())[0]
    row.reserved = row.reserved + 1
    winner.update(row)
    winner.commit()

    with pytest.raises(psycopg2.errors.SerializationFailure):
        loser.all(query.for_update())

    loser.rollback()


# --- the savepoint -------------------------------------------------------------------------------


def _decline(amount: Decimal) -> None:
    """A payment processor that says no. The failure `settle` is built to survive."""
    raise usecases.PaymentDeclined(f"the card was declined for {amount}")


def test_a_declined_payment_releases_the_hold_and_leaves_the_invoice_standing(
    postgres_pair: tuple[SnakeSession, SnakeSession],
) -> None:
    """THE SAVEPOINT, in the only situation that shows what it does: half the operation survives.

    `settle` issues the invoice, then guards the rest — payment, shipment, final state — inside a
    savepoint. The charge is declined, so `ROLLBACK TO SAVEPOINT` takes those three back and leaves
    the invoice where it was, because an issued invoice is a document and not a wish.

    Then the part a plain `rollback()` could never do: the transaction is STILL ALIVE, so the release
    of the hold is written on top of what survived and committed with it. Everything below is read on
    the OTHER connection, which is what makes "committed" mean committed rather than merely visible
    to the session that wrote it.

    Without the savepoint there is no version of this that works. A `rollback()` would throw the
    invoice away as well, and — in Postgres — a failed statement poisons the whole transaction, so
    the release could not be written at all afterwards. The units would stay promised to an order
    that is never going to ship, and nothing anywhere would say so.
    """
    seller, auditor = postgres_pair
    contest = _contest(seller, on_hand=5, wanted=2)
    reserved = usecases.reserve(seller, order_id=contest.first_order)
    assert not isinstance(reserved, Failure), reserved
    assert _levels(seller, contest) == (5, 2)

    declined = usecases.settle(
        seller,
        order_id=contest.first_order,
        subscription_id=contest.first_subscription,
        charge=_decline,
    )

    assert declined == Failure("payment_declined")
    # The hold is gone and the shelf never moved: exactly the state the reservation started from.
    assert _levels(auditor, contest) == (5, 0)
    # The invoice SURVIVED the rewind, unpaid, and nothing was ever shipped or paid.
    invoices = auditor.all(SnakeQuery(Invoice))
    assert [invoice.paid for invoice in invoices] == [False]
    assert auditor.all(SnakeQuery(Payment)) == []
    assert (
        auditor.all(
            SnakeQuery(StockMovement).filter(
                StockMovement.reason == MovementReason.SALE
            )
        )
        == []
    )
    # The order kept the invoice it was billed against, and did NOT reach SETTLED.
    order = auditor.first(SnakeQuery(Order).filter(Order.id == contest.first_order))
    assert order is not None
    assert order.state is OrderState.INVOICED
    assert order.invoice_id == invoices[0].id


def test_the_released_units_can_be_promised_to_the_next_customer(
    postgres_pair: tuple[SnakeSession, SnakeSession],
) -> None:
    """The release is worth something only if somebody else can now have the units. They can.

    It closes the loop the savepoint exists for. A compensation that landed in the database but left
    the availability unchanged would be a write that looks right and buys nothing — and this is the
    assertion that would catch it, from the other connection, which is the only place the answer
    counts.
    """
    seller, rival = postgres_pair
    contest = _contest(seller, on_hand=1, wanted=1)
    assert not isinstance(
        usecases.reserve(seller, order_id=contest.first_order), Failure
    )
    assert usecases.reserve(rival, order_id=contest.second_order) == Failure("conflict")

    declined = usecases.settle(
        seller,
        order_id=contest.first_order,
        subscription_id=contest.first_subscription,
        charge=_decline,
    )
    assert declined == Failure("payment_declined")

    second = usecases.reserve(rival, order_id=contest.second_order)

    assert not isinstance(second, Failure), second
    assert second.state is OrderState.RESERVED
    assert _levels(seller, contest) == (1, 1)


def test_the_stale_instances_after_a_rewind_do_not_reach_the_database(
    postgres_pair: tuple[SnakeSession, SnakeSession],
) -> None:
    """The gotcha that cost the most here: `ROLLBACK TO SAVEPOINT` rewinds ROWS, not Python objects.

    This ORM has no identity map and no unit of work, by design. So after the rewind the `Stock`
    instances the shipment mutated still carry the shipped numbers, while the rows behind them are
    back to what they were, and a compensation that did arithmetic on those instances would commit a
    number derived from a state that no longer exists. It would not raise; it would just be wrong.

    Five on the shelf, two promised, a declined charge: the arithmetic on stale objects would write
    `reserved = 0 - 2` and be stopped by the engine's CHECK, or on a bigger hold land a plausible
    wrong number in silence. What the operation actually does is RE-READ the rows, which is what this
    number proves.
    """
    seller, auditor = postgres_pair
    contest = _contest(seller, on_hand=5, wanted=2)
    assert not isinstance(
        usecases.reserve(seller, order_id=contest.first_order), Failure
    )

    assert usecases.settle(
        seller,
        order_id=contest.first_order,
        subscription_id=contest.first_subscription,
        charge=_decline,
    ) == Failure("payment_declined")

    assert _levels(auditor, contest) == (5, 0)


# --- the happy path, on the engine the demos actually deploy on ----------------------------------


def test_settling_against_a_real_engine_moves_the_money_and_the_goods(
    postgres_pair: tuple[SnakeSession, SnakeSession],
) -> None:
    """The whole flow on Postgres, read from the OTHER connection: place, reserve, settle, committed.

    The same path the SQLite file pins, run where it will actually be deployed and checked from
    outside the transaction that wrote it. It is the control for everything above: if this were red
    too, the failure tests would be proving nothing about savepoints and everything about a broken
    operation.
    """
    seller, auditor = postgres_pair
    contest = _contest(seller, on_hand=5, wanted=2)
    assert not isinstance(
        usecases.reserve(seller, order_id=contest.first_order), Failure
    )

    settled = usecases.settle(
        seller,
        order_id=contest.first_order,
        subscription_id=contest.first_subscription,
    )

    assert not isinstance(settled, Failure), settled
    assert _levels(auditor, contest) == (3, 0)
    order = auditor.first(SnakeQuery(Order).filter(Order.id == contest.first_order))
    assert order is not None
    assert order.state is OrderState.SETTLED
    invoices = auditor.all(SnakeQuery(Invoice))
    assert [(invoice.paid, invoice.amount_cents) for invoice in invoices] == [
        (True, 2000)
    ]


# --- The same two properties, asked of the ASYNCHRONOUS session -------------------------------
#
# `shared/aio/orders_usecases.py` is a second orchestration of these operations, and the nets that
# guard it —`test_async_mirror.py` and `test_sync_async_parity.py`— both run on SQLite. That is
# enough for the reads and the plain writes and it is NOT enough for these two: SQLite answers
# `Nope` to row locking, so the parity run never emits `SET TRANSACTION` and never takes a lock. The
# asynchronous `set_isolation` and the asynchronous `savepoint` would therefore be covered by tests
# that call them directly in `src/test` and by no application path at all — which is the state this
# whole `frameworks/` layer exists to leave behind.
#
# So the two properties that only a real Postgres can show are asked of BOTH colours, here, side by
# side. The third connection is the asynchronous one; the two synchronous sessions build the data
# and audit the result, so "committed" keeps meaning committed on somebody else's connection.


async def _decline_async(amount: Decimal) -> None:
    """The asynchronous processor that says no. Awaited, because taking money is I/O."""
    raise usecases.PaymentDeclined(f"the card was declined for {amount}")


def test_the_asynchronous_declined_payment_leaves_what_the_synchronous_one_leaves(
    postgres_pair: tuple[SnakeSession, SnakeSession],
    postgres_schema: str,
) -> None:
    """THE ASYNCHRONOUS SAVEPOINT, in the one situation that shows what it does.

    The same assertions as `test_a_declined_payment_releases_the_hold_and_leaves_the_invoice_standing`
    above, driven by an `AsyncSession` against the same real Postgres — because the property being
    checked is not "the method exists" but "the rewind takes back exactly three of the four steps and
    the transaction survives it", and that cannot be seen on an engine where the operation never
    declares an isolation level.

    The compensation RE-READS the stock rows, and this is where that matters most. A rollback to
    savepoint rewinds the DATABASE and not the Python objects: the instances the shipment mutated
    still carry the shipped numbers afterwards. Trusting them raises nothing at all — it commits a
    `reserved` computed from a state that was rolled back — so the only way to know the asynchronous
    twin does the re-read is to read the row back from ANOTHER connection, which is what `auditor`
    is for.
    """
    seller, auditor = postgres_pair
    contest = _contest(seller, on_hand=5, wanted=2)

    async def settle_it() -> object:
        driver = await AsyncPsycopgDriver.connect(postgres_schema)
        session = AsyncSession(driver, PostgresDialect())
        try:
            reserved = await aio.orders_usecases.reserve(
                session, order_id=contest.first_order
            )
            assert not isinstance(reserved, Failure), reserved
            return await aio.orders_usecases.settle(
                session,
                order_id=contest.first_order,
                subscription_id=contest.first_subscription,
                charge=_decline_async,
            )
        finally:
            await session.close()

    declined = asyncio.run(settle_it())

    assert declined == Failure("payment_declined")
    # The hold is gone and the shelf never moved: exactly the state the reservation started from.
    assert _levels(auditor, contest) == (5, 0)
    # The invoice SURVIVED the rewind, unpaid, and nothing was ever shipped or paid.
    invoices = auditor.all(SnakeQuery(Invoice))
    assert [invoice.paid for invoice in invoices] == [False]
    assert auditor.all(SnakeQuery(Payment)) == []
    assert (
        auditor.all(
            SnakeQuery(StockMovement).filter(
                StockMovement.reason == MovementReason.SALE
            )
        )
        == []
    )
    order = auditor.first(SnakeQuery(Order).filter(Order.id == contest.first_order))
    assert order is not None
    assert order.state is OrderState.INVOICED
    assert order.invoice_id == invoices[0].id


def test_the_asynchronous_reservation_waits_for_the_row_somebody_else_is_holding(
    postgres_pair: tuple[SnakeSession, SnakeSession],
    postgres_schema: str,
) -> None:
    """The asynchronous `reserve` BLOCKS on a stock row another connection has locked.

    The synchronous twin above proves the lock is real by removing it and watching the test go green
    for the wrong reason. This one proves the asynchronous path takes the SAME lock, and it is not a
    formality: `locking_stock_query` decides `for_update` from the DIALECT rather than the session
    precisely so that both colours ask the engine the same question — and a decision made in two
    places is a decision that can be made differently in one of them.

    The `statement_timeout` is set on the asynchronous connection because that is the one that has to
    wait, and it is committed before the operation starts: `reserve` opens with `SET TRANSACTION` and
    Postgres refuses that once a connection has work in flight.
    """
    import psycopg

    _, rival = postgres_pair
    contest = _contest(rival)
    rival.commit()
    # The rival holds ONLY the read lock, taken with the very selector the operation uses: this is
    # the moment `reserve` sits in between taking its rows and deciding, not an impression of it.
    inventory_selectors.lock_stock(
        rival, warehouse_id=contest.warehouse_id, sku_ids=[contest.sku_id]
    )

    async def reserve_it() -> None:
        driver = await AsyncPsycopgDriver.connect(postgres_schema)
        session = AsyncSession(driver, PostgresDialect())
        try:
            await driver.execute(f"SET statement_timeout = '{_PATIENCE}'", ())
            await driver.commit()
            await aio.orders_usecases.reserve(session, order_id=contest.second_order)
        finally:
            await session.close()

    with pytest.raises(psycopg.errors.QueryCanceled):
        asyncio.run(reserve_it())

    rival.rollback()
