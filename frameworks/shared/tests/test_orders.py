"""The orders domain end to end: the joint between `inventory` and `billing`, and its second pair key.

`orders` is the ninth and last domain, and it exists because the other two never touched each other.
Stock was moved by a `receive` nobody had ordered, and an invoice was issued against a subscription
that had bought nothing. Between them there was no row that said "this customer wants these units
from this warehouse", which is the row every interesting failure hangs off: two customers competing
for the same unit, and an invoice that must not survive a reservation that got rolled back.

What is pinned here is what phase 2 owns: the shape and the plain writes. The multi-step operations
—reserving under a lock, settling inside a savepoint— are phase 3 and need a real Postgres, because
this suite runs on SQLite and SQLite answers `Nope` to row locking. Testing them here would prove
that the calls exist, which was never in doubt.

Two things get special attention. The COMPOSITE key of `OrderLine` is the second one in the repo, and
that is the point: `Stock`'s pair carries a quantity and this one carries money, so the shape is not
a one-off of the inventory. And the cross-domain reads are counted with `assert_queries`, because an
order that walks to its customer, its warehouse and its invoice is exactly the page that turns into
four statements per row the day somebody drops an `include`.
"""

from __future__ import annotations

from datetime import date, time, timedelta, timezone
from decimal import Decimal

from snakeorm import SnakeUtc, SnakeQuery, SnakeSession
from snakeorm.debug import assert_queries

from shared.models import (
    Invoice,
    OrderLine,
    OrderState,
    Plan,
    Sku,
    SkuKind,
    Stock,
    Subscription,
    User,
)
from shared.usecases import inventory_usecases as inventory
from shared.usecases import orders_usecases as usecases
from shared.usecases.result import Failure


def _customer(session: SnakeSession, username: str = "buyer") -> int:
    """A user to buy things. Orders hang off `accounts`, which is the root of the whole graph."""
    user = session.add(
        User(username=username, email=f"{username}@demo.dev", password_hash="x")
    )
    session.commit()
    return user.id


def _warehouse(session: SnakeSession, code: str = "MAD") -> int:
    """A warehouse to ship from. It is built through the inventory use case, not by hand: the two
    domains share one graph, and a fixture that inserted its own row would be testing a copy."""
    warehouse = inventory.create_warehouse(
        session,
        code=code,
        name=f"Warehouse {code}",
        opened_on=date(2020, 3, 14),
        shift_start=time(6, 30),
        cutoff=time(18, 0, tzinfo=timezone(timedelta(hours=1))),
    )
    assert not isinstance(warehouse, Failure)
    return warehouse.id


def _sku(session: SnakeSession, name: str = "Widget", price: str = "10.00") -> int:
    """A stockable item with a price, which is what a line copies at the moment of ordering."""
    sku = inventory.create_sku(
        session,
        name=name,
        kind=SkuKind.PHYSICAL,
        price=Decimal(price),
        weight_kg=1.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(sku, Failure)
    return sku.id


def _placed(
    session: SnakeSession,
    *,
    reference: str = "ORD-1",
    customer_id: int | None = None,
    warehouse_id: int | None = None,
    lines: list[tuple[int, int]] | None = None,
) -> int:
    """An order already in the database, with its lines. Returns its id."""
    customer_id = _customer(session) if customer_id is None else customer_id
    warehouse_id = _warehouse(session) if warehouse_id is None else warehouse_id
    lines = [(_sku(session), 2)] if lines is None else lines
    order = usecases.place_order(
        session,
        reference=reference,
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        lines=lines,
    )
    assert not isinstance(order, Failure), order
    return order.id


def test_the_order_carries_its_money_state_and_instant(session: SnakeSession) -> None:
    """Every type the order declares comes back EQUAL and as the type that was declared.

    On SQLite a `Decimal` is TEXT and a `SnakeUtc` is TEXT too, so a total that comes back as a
    `Decimal` of the same value is the coercion doing its job rather than the engine.
    """
    order_id = _placed(session, lines=[(_sku(session, price="19.99"), 3)])

    order = usecases.get_order(session, order_id)

    assert not isinstance(order, Failure)
    assert order.reference == "ORD-1"
    assert order.state is OrderState.DRAFT
    assert order.total == Decimal("59.97") and isinstance(order.total, Decimal)
    assert order.invoice_id is None
    assert order.placed_at is not None


def test_a_line_is_identified_by_the_pair_of_order_and_sku(
    session: SnakeSession,
) -> None:
    """Ordering the same SKU twice raises the quantity: it does not open a second line.

    That IS the composite key. With a surrogate id both writes would land and the question the
    reservation asks —how many units of this SKU does this order want— would stop having one answer.
    """
    sku_id = _sku(session)
    order_id = _placed(session, lines=[(sku_id, 2)])

    usecases.set_line(session, order_id=order_id, sku_id=sku_id, quantity=5)

    lines = usecases.order_lines(session, order_id)
    assert not isinstance(lines, Failure)
    assert [(line.sku_id, line.quantity) for line in lines] == [(sku_id, 5)]


def test_the_same_sku_lives_in_two_different_orders(session: SnakeSession) -> None:
    """The pair is the identity, so the SAME SKU in ANOTHER order is a different line, not a clash.

    Half a composite key is not a key: a unique index on `sku_id` alone would let one customer's
    order block everybody else's, and it would only show up with a second customer.
    """
    customer_id, warehouse_id = _customer(session), _warehouse(session)
    sku_id = _sku(session)
    first = _placed(
        session,
        reference="ORD-1",
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        lines=[(sku_id, 1)],
    )
    second = _placed(
        session,
        reference="ORD-2",
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        lines=[(sku_id, 4)],
    )

    assert [
        line.quantity
        for order in (first, second)
        for line in _lines(usecases.order_lines(session, order))
    ] == [1, 4]


def _lines(result: list[OrderLine] | Failure) -> list[OrderLine]:
    """Unwraps a `list[OrderLine] | Failure` so the assertion that follows reads as one line.

    Typed rather than `object`: the whole point of this ORM is that the type survives the round trip,
    and a helper that widened it here would hide exactly the thing the suite exists to prove.
    """
    assert not isinstance(result, Failure), result
    return result


def test_placing_an_order_totals_its_lines(session: SnakeSession) -> None:
    """The total is COMPUTED from the lines and the SKU prices, not passed in by the caller.

    A total that arrives from a form is a number the customer chose. The price is read from the SKU
    at the moment of ordering and copied onto the line, which is what makes an old order still add up
    after the catalogue is repriced.
    """
    first, second = _sku(session, "A", "3.50"), _sku(session, "B", "10.00")

    order_id = _placed(session, lines=[(first, 2), (second, 1)])

    order = usecases.get_order(session, order_id)
    assert not isinstance(order, Failure)
    assert order.total == Decimal("17.00")


def test_an_order_with_no_lines_is_refused(session: SnakeSession) -> None:
    """An order of nothing is not an order: it would reserve nothing and invoice zero."""
    refused = usecases.place_order(
        session,
        reference="ORD-9",
        customer_id=_customer(session),
        warehouse_id=_warehouse(session),
        lines=[],
    )

    assert refused == Failure("missing_fields")


def test_a_line_of_zero_units_is_refused(session: SnakeSession) -> None:
    """Zero units is not an operation and a negative one is a return written the wrong way round."""
    refused = usecases.place_order(
        session,
        reference="ORD-9",
        customer_id=_customer(session),
        warehouse_id=_warehouse(session),
        lines=[(_sku(session), 0)],
    )

    assert refused == Failure("missing_fields")


def test_an_order_for_an_unknown_customer_writes_nothing(
    session: SnakeSession,
) -> None:
    """The three references are checked BEFORE the first write, so there is nothing to undo.

    The engine would refuse too — they are foreign keys — but from inside a commit, with a driver
    error, three layers under the form that asked.
    """
    refused = usecases.place_order(
        session,
        reference="ORD-9",
        customer_id=999,
        warehouse_id=_warehouse(session),
        lines=[(_sku(session), 1)],
    )

    assert refused == Failure("not_found")
    assert usecases.list_orders(session) == []


def test_an_order_for_an_unknown_warehouse_or_sku_is_not_found(
    session: SnakeSession,
) -> None:
    """The warehouse and every SKU on the lines have to exist: half a key resolves to nothing."""
    customer_id = _customer(session)

    assert usecases.place_order(
        session,
        reference="ORD-9",
        customer_id=customer_id,
        warehouse_id=999,
        lines=[(_sku(session), 1)],
    ) == Failure("not_found")
    assert usecases.place_order(
        session,
        reference="ORD-8",
        customer_id=customer_id,
        warehouse_id=_warehouse(session, "BCN"),
        lines=[(999, 1)],
    ) == Failure("not_found")


def test_a_repeated_reference_is_a_conflict(session: SnakeSession) -> None:
    """The reference is what a human quotes on the phone, so it is unique and the clash is answered.

    The unique index holds it under two writers; this is what turns the second attempt into something
    a form can print instead of an `IntegrityError`.
    """
    customer_id, warehouse_id = _customer(session), _warehouse(session)
    sku_id = _sku(session)
    _placed(
        session,
        reference="ORD-1",
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        lines=[(sku_id, 1)],
    )

    refused = usecases.place_order(
        session,
        reference="ORD-1",
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        lines=[(sku_id, 1)],
    )

    assert refused == Failure("conflict")


def test_the_cross_domain_relations_come_in_one_statement(
    session: SnakeSession,
) -> None:
    """An order listing walks to `accounts`, to `inventory` and to `billing` in ONE select.

    The three are to-one, so they are LEFT JOINs on the same statement and the cost of the page does
    not depend on how many orders it shows. Counted rather than asserted by eye: this is the read
    where dropping an `include` still renders and just costs three more queries per row.
    """
    customer_id, warehouse_id = _customer(session), _warehouse(session)
    for index in range(4):
        _placed(
            session,
            reference=f"ORD-{index}",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            lines=[(_sku(session, f"Widget {index}"), 1)],
        )

    with assert_queries(1):
        orders = usecases.list_orders(session)
        assert [order.customer.username for order in orders] == ["buyer"] * 4
        assert [order.warehouse.code for order in orders] == ["MAD"] * 4
        assert [order.invoice for order in orders] == [None] * 4


def test_the_lines_of_many_orders_load_in_one_extra_statement(
    session: SnakeSession,
) -> None:
    """The to-many is a select-in: ONE more statement for the lot, not one per order.

    Three statements, and each one is named: the use case checks the customer exists so it can answer
    404, the listing fetches the orders, and the select-in fetches every line of all four in one go.
    N+1 would be six, and four orders is enough to tell six from three while still being small enough
    that the failure names the bug instead of drowning it.
    """
    customer_id, warehouse_id = _customer(session), _warehouse(session)
    for index in range(4):
        _placed(
            session,
            reference=f"ORD-{index}",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            lines=[(_sku(session, f"Widget {index}"), index + 1)],
        )

    with assert_queries(3):
        orders = usecases.orders_of_customer(session, customer_id)
        assert not isinstance(orders, Failure)
        assert [len(order.lines) for order in orders] == [1, 1, 1, 1]


def test_an_unknown_order_is_not_found_rather_than_empty(
    session: SnakeSession,
) -> None:
    """Asking about something that is not there is a `not_found`, not an empty answer."""
    assert usecases.get_order(session, 999) == Failure("not_found")
    assert usecases.order_lines(session, 999) == Failure("not_found")
    assert usecases.orders_of_customer(session, 999) == Failure("not_found")


def test_cancelling_a_draft_order_moves_it_to_cancelled(session: SnakeSession) -> None:
    """A cancellation is a state change and not a deletion: the order is history the moment it exists."""
    order_id = _placed(session)

    cancelled = usecases.cancel_order(session, order_id=order_id)

    assert not isinstance(cancelled, Failure)
    assert cancelled.state is OrderState.CANCELLED


def test_a_billed_order_cannot_be_cancelled(session: SnakeSession) -> None:
    """Once an invoice is attached, cancelling is a refund — another operation, with its own money.

    The refusal lives here and not in the template, because it is the rule and not the button. A
    disabled button is a suggestion; this is what happens when somebody posts the form anyway.
    """
    order_id = _placed(session)
    usecases.attach_invoice(session, order_id=order_id, invoice_id=_invoice(session))

    refused = usecases.cancel_order(session, order_id=order_id)

    assert refused == Failure("conflict")


def _invoice(session: SnakeSession, tag: str = "one") -> int:
    """An invoice from the BILLING domain, to hang a billed order off.

    It is built with the ORM directly and not through the billing use case because what is being
    proved here is the JOINT —that an order can point at an invoice— and not how invoices come to be.
    Every part of it is tagged, because a plan name, a username and an email are all unique and a
    second invoice in the same test would otherwise fail on the wrong constraint.
    """
    plan = session.add(Plan(name=f"plan-{tag}", price_cents=900))
    session.commit()
    subscription = session.add(
        Subscription(
            user_id=_customer(session, f"payer-{tag}"),
            plan_id=plan.id,
            started_at=SnakeUtc.now(),
        )
    )
    session.commit()
    invoice = session.add(
        Invoice(
            amount_cents=900,
            subscription_id=subscription.id,
            issued_at=SnakeUtc.now(),
        )
    )
    session.commit()
    return invoice.id


def test_the_settled_order_carries_its_invoice(session: SnakeSession) -> None:
    """The joint with `billing`, loaded: a settled order navigates to the invoice that closed it.

    The FK is NULLABLE, so the relationship is a LEFT JOIN and an order with no invoice is still a
    row on the listing rather than one that vanishes from it.
    """
    order_id = _placed(session)
    invoice_id = _invoice(session)

    usecases.attach_invoice(session, order_id=order_id, invoice_id=invoice_id)

    order = usecases.get_order(session, order_id)
    assert not isinstance(order, Failure)
    assert order.state is OrderState.INVOICED
    assert order.invoice is not None
    assert order.invoice.amount_cents == 900


def test_attaching_an_invoice_that_is_not_there_writes_nothing(
    session: SnakeSession,
) -> None:
    """A `not_found` for the invoice, not a foreign key violation raised inside the commit."""
    order_id = _placed(session)

    refused = usecases.attach_invoice(session, order_id=order_id, invoice_id=999)

    assert refused == Failure("not_found")
    order = usecases.get_order(session, order_id)
    assert not isinstance(order, Failure)
    assert order.invoice_id is None


def test_a_billed_order_will_not_take_a_second_invoice(session: SnakeSession) -> None:
    """Re-billing an order is not an edit: the first invoice already describes what it contains."""
    order_id = _placed(session)
    usecases.attach_invoice(session, order_id=order_id, invoice_id=_invoice(session))

    refused = usecases.attach_invoice(
        session, order_id=order_id, invoice_id=_invoice(session, "two")
    )

    assert refused == Failure("conflict")


def test_an_order_with_lines_is_not_deleted_but_refused(session: SnakeSession) -> None:
    """FK RESTRICT said in the ORM's own words: an order's lines are what it was.

    The engine would refuse anyway. Refusing first is what lets a delete page explain that the order
    has to be emptied —or cancelled, which is what one actually wants— instead of showing a stack
    trace from inside a commit.
    """
    order_id = _placed(session)

    refused = usecases.remove_order(session, order_id=order_id)

    assert refused == Failure("conflict")
    assert usecases.get_order(session, order_id) != Failure("not_found")


def test_an_emptied_order_can_be_deleted(session: SnakeSession) -> None:
    """With no lines left there is nothing to orphan, so the row goes."""
    sku_id = _sku(session)
    order_id = _placed(session, lines=[(sku_id, 1)])
    usecases.remove_line(session, order_id=order_id, sku_id=sku_id)

    removed = usecases.remove_order(session, order_id=order_id)

    assert removed is None
    assert usecases.list_orders(session) == []


def test_removing_a_line_that_is_not_there_says_so(session: SnakeSession) -> None:
    """A delete that deleted nothing is worth knowing about; both halves of the key are required."""
    order_id = _placed(session)

    assert usecases.remove_line(session, order_id=order_id, sku_id=999) == Failure(
        "not_found"
    )
    assert usecases.remove_line(session, order_id=999, sku_id=1) == Failure("not_found")


def test_a_line_set_to_zero_units_is_refused(session: SnakeSession) -> None:
    """Setting a line to zero is removing it, and saying so is the caller's job, not a guess here."""
    sku_id = _sku(session)
    order_id = _placed(session, lines=[(sku_id, 1)])

    refused = usecases.set_line(session, order_id=order_id, sku_id=sku_id, quantity=0)

    assert refused == Failure("missing_fields")


def test_changing_a_line_retotals_the_order(session: SnakeSession) -> None:
    """The total is derived, so every write that touches a line has to leave it derived.

    A total that only gets recomputed on creation is right exactly once, and wrong from the first
    edit onwards — silently, because nothing about the row looks broken.
    """
    sku_id = _sku(session, price="4.00")
    order_id = _placed(session, lines=[(sku_id, 2)])

    usecases.set_line(session, order_id=order_id, sku_id=sku_id, quantity=5)

    order = usecases.get_order(session, order_id)
    assert not isinstance(order, Failure)
    assert order.total == Decimal("20.00")


def test_the_report_counts_and_totals_per_state(session: SnakeSession) -> None:
    """`GROUP BY state` with a COUNT and a SUM: one row per state, in one statement.

    It is not a `@snake_result`, and that is not an omission: a `@snake_result` is a row of a MODEL
    plus scalars, and there is no state table to be the row. What the report groups by is a value.
    """
    customer_id, warehouse_id = _customer(session), _warehouse(session)
    sku_id = _sku(session, price="10.00")
    for index in range(3):
        _placed(
            session,
            reference=f"ORD-{index}",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            lines=[(sku_id, 1)],
        )
    usecases.cancel_order(session, order_id=usecases.list_orders(session)[0].id)

    report = usecases.orders_per_state(session)

    assert {state: count for state, count, _ in report} == {
        OrderState.CANCELLED: 1,
        OrderState.DRAFT: 2,
    }


def test_the_customer_rollup_comes_typed_and_in_one_statement(
    session: SnakeSession,
) -> None:
    """`annotate` gives back the user plus their aggregates, in ONE statement and no query per customer.

    The money is compared by VALUE and not by type, and that is not laziness. `Decimal` is a DEGRADED
    type on SQLite —it is stored as TEXT— so `SUM` over it comes back as a float, and the coercion
    deliberately refuses to build a `Decimal` out of a float: going through binary floating point is
    the exact thing a `Decimal` exists to avoid. On Postgres the same call sums a `NUMERIC` and the
    driver hands back a `Decimal`. The value is right on both; the type is only right on the engine
    that has the type. Asserting `isinstance` here would be asserting the engine, not the ORM.
    """
    customer_id, warehouse_id = _customer(session), _warehouse(session)
    sku_id = _sku(session, price="10.00")
    for index in range(2):
        _placed(
            session,
            reference=f"ORD-{index}",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            lines=[(sku_id, 2)],
        )

    rollup = usecases.customer_orders(session)

    mine = [row for row in rollup if row.customer.id == customer_id]
    assert [(row.order_count, row.ordered_total) for row in mine] == [
        (2, Decimal("40.00"))
    ]


def test_the_pager_clamps_a_page_nobody_can_be_on(session: SnakeSession) -> None:
    """`page` arrives from a URL, so it is whatever somebody typed there: it is clamped, not trusted."""
    customer_id, warehouse_id = _customer(session), _warehouse(session)
    for index in range(3):
        _placed(
            session,
            reference=f"ORD-{index}",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            lines=[(_sku(session, f"Widget {index}"), 1)],
        )

    page = usecases.paginate_orders(session, page=99, per_page=2)

    assert (page.total, page.page, page.pages) == (3, 2, 2)
    assert len(page.rows) == 1


def test_the_seed_leaves_every_state_on_the_board(seeded: SnakeSession) -> None:
    """Phase 3 needs the situations to be THERE, not to be built by the operation that tests them.

    An `orders` seed that only wrote drafts would make the settle path untestable without first
    writing a fixture that walks the whole flow — and a fixture that walks the flow is testing itself.
    """
    states = {order.state for order in usecases.list_orders(seeded)}

    assert states == set(OrderState)


def test_the_seed_leaves_an_order_that_cannot_be_reserved(seeded: SnakeSession) -> None:
    """At least one order asks for more units than its warehouse holds: the case `reserve` refuses.

    Without it, phase 3's refusal path would only ever be reachable by hand-editing the data, which
    is the same as not having the case at all.
    """
    over = [
        (order.reference, line.sku_id, line.quantity)
        for order in usecases.list_orders(seeded)
        for line in _lines(usecases.order_lines(seeded, order.id))
        if _available(seeded, order.warehouse_id, line.sku_id) < line.quantity
    ]

    assert over, "no seeded order asks for more than its warehouse holds"


def _available(session: SnakeSession, warehouse_id: int, sku_id: int) -> int:
    """How many units of a SKU a warehouse holds. Zero if that pair holds nothing at all."""
    row = session.first(
        SnakeQuery(Stock).filter(
            Stock.warehouse_id == warehouse_id, Stock.sku_id == sku_id
        )
    )
    return 0 if row is None else row.on_hand


def test_the_seed_leaves_a_settled_order_with_its_invoice(seeded: SnakeSession) -> None:
    """The joint with `billing` is seeded, not only declared: a settled order points at an invoice."""
    settled = [
        order
        for order in usecases.list_orders(seeded)
        if order.state is OrderState.SETTLED
    ]

    assert settled
    assert all(order.invoice is not None for order in settled)


def test_the_seeded_lines_point_at_skus_the_warehouse_stocks(
    seeded: SnakeSession,
) -> None:
    """A line whose warehouse never stocked that SKU makes the reservation meaningless, not hard.

    The seeder gives each warehouse HALF the catalogue, so picking the SKU at random from the whole
    catalogue would leave most lines with no stock row to lock at all — and phase 3's `for_update`
    would be locking nothing while the test went green.
    """
    pairs = {(row.warehouse_id, row.sku_id) for row in seeded.all(SnakeQuery(Stock))}
    lines = [
        (order.warehouse_id, line.sku_id)
        for order in usecases.list_orders(seeded)
        for line in _lines(usecases.order_lines(seeded, order.id))
    ]

    assert lines
    assert all(pair in pairs for pair in lines)


def test_the_seeded_totals_match_their_lines(seeded: SnakeSession) -> None:
    """The seed writes the same total the use case would compute: one arithmetic, not two."""
    skus = {sku.id: sku.price for sku in seeded.all(SnakeQuery(Sku))}
    for order in usecases.list_orders(seeded)[:20]:
        lines = _lines(usecases.order_lines(seeded, order.id))
        expected = sum(
            (skus[line.sku_id] * line.quantity for line in lines), Decimal("0")
        )
        assert order.total == expected, order.reference
