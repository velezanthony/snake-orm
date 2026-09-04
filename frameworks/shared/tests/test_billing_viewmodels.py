"""The view models of `billing`: three pages, three tables deep, and money that stays exact.

`test_viewmodels.py` pins the pilot's four rules and everything it says applies here. What this
domain adds is two things neither of the others has.

THE FIRST IS DEPTH. An invoice row shows the customer's name and the plan's name, and neither of
those is one hop away: `invoice -> subscription -> plan` and `invoice -> subscription -> user` are
two-step to-one navigations, the deepest in this repository. They are the strongest case for the rule
this whole layer exists to enforce, because a template writing `invoice.subscription.plan.name` does
not look like an N+1 — it looks like reading an attribute — and it fires TWO relation loads per row
inside the renderer, where nothing counts queries. So the depth is flattened here and the budget
tests below say what that cost: one statement, whatever the page shows.

THE SECOND IS MONEY, and it is the reason this module owns a formatter the orders pages call. Billing
stores integer CENTS and orders stores a `NUMERIC(12,2)`; both are exact, and the conversion between
them is the one place a float could sneak into a value somebody checks against a bank statement.
`Decimal(cents) / 100` is the conversion; `cents / 100` is the bug; and having ONE function rather
than two is what stops the second one being written later, somewhere else, by somebody who did not
read this paragraph.

The detail page's arithmetic gets its own tests for a reason that is not about formatting at all. An
invoice carries a `paid` FLAG and a list of partial PAYMENTS, and nothing in the schema forces the
two to agree. An invoice marked settled with half of it collected is a row the database will hold
happily forever, and this page is the only thing in the demos that shows it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, datetime
from decimal import Decimal

from snakeorm import SnakeModel, SnakeSession, SnakeUtc
from snakeorm.debug import capture_queries

from shared.models import Invoice, Plan, User
from shared.services.billing_services import PAYMENT_KINDS
from shared.usecases import billing_usecases as usecases
from shared.usecases.result import Failure
from shared.viewmodels import billing_viewmodels as viewmodels

# What a template is allowed to receive. `bool` is listed for the reader even though it is an `int`.
_PRIMITIVES = (str, int, bool, type(None))

_WHEN = SnakeUtc(2024, 5, 17, 9, 30)

# A cutoff AFTER every fixture date, so the report's older figures answer exactly what they
# answered before the ageing section existed. The tests that are about the ageing pass their own.
_LATER = SnakeUtc(2024, 12, 31, 0, 0)


def _leaves(value: object) -> Iterator[object]:
    """Every leaf of a page dict, walking through the dicts and lists it nests."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _leaves(item)
    else:
        yield value


def _assert_only_primitives(page: object) -> None:
    """Asserts that the whole page is made of primitives, naming the offender when it is not."""
    for leaf in _leaves(page):
        assert not isinstance(leaf, SnakeModel), (
            f"a model reached the template: {leaf!r}"
        )
        assert not isinstance(leaf, (datetime, date)), f"an unformatted date: {leaf!r}"
        assert not isinstance(leaf, Decimal), f"an unformatted decimal: {leaf!r}"
        assert isinstance(leaf, _PRIMITIVES), f"not a primitive: {type(leaf)} {leaf!r}"


def _account(session: SnakeSession, *, username: str, plan: str, cents: int) -> int:
    """A user on a plan, subscribed through the use case. Returns the subscription id.

    The `User` and the `Plan` are added directly because this repository has no use case that creates
    either — the same two exceptions `test_orders_viewmodels.py` makes, for the same reason.
    """
    user = session.add(
        User(username=username, email=f"{username}@demo.dev", password_hash="x")
    )
    tariff = session.add(Plan(name=plan, price_cents=cents))
    session.commit()
    return usecases.subscribe(session, user.id, tariff.id).id


def _invoice(session: SnakeSession, subscription_id: int, cents: int) -> Invoice:
    """One invoice raised through the use case, with its date pinned so ordering is reproducible."""
    invoice = usecases.issue_invoice(session, subscription_id, cents)
    invoice.issued_at = _WHEN
    session.update(invoice)
    session.commit()
    return invoice


def _pay(session: SnakeSession, invoice: Invoice, cents: int, method: str) -> None:
    """A PARTIAL payment written directly, which is the only way to make one.

    `pay_invoice` settles an invoice in full — it writes the payment AND flips the flag — and the
    interesting case here is precisely the one it cannot produce: an invoice whose payments do not
    add up to what it says. Going through the use case would make every test agree by construction
    and the page's whole reason to exist would go untested.

    The KIND goes through the same mapping the use case uses. Writing the payment directly is the
    exception this helper exists for; inventing a second way to decide what a `card` is would not be.
    """
    kind = PAYMENT_KINDS[method]
    session.add(kind(amount_cents=cents, invoice_id=invoice.id, paid_at=_WHEN))
    session.commit()


# ---- Only primitives come out ---------------------------------------------------------------------


def test_the_list_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The listing hands the template strings and numbers, never an `Invoice` nor its plan."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)

    _assert_only_primitives(viewmodels.invoice_list(session))


def test_the_detail_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The detail hands over strings and numbers, payments included."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    invoice = _invoice(session, subscription_id, 4200)
    _pay(session, invoice, 4200, "card")

    _assert_only_primitives(viewmodels.invoice_detail(session, invoice.id))


def test_the_report_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The report hands over strings and numbers, never a `Plan` nor a raw count of cents."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)

    _assert_only_primitives(viewmodels.billing_report(session, _LATER))


# ---- The three hops the template no longer makes ---------------------------------------------------


def test_the_row_carries_the_customer_and_the_plan_already_flattened(
    session: SnakeSession,
) -> None:
    """Two-step navigations, resolved here: `subscription.user` and `subscription.plan`.

    This is the deepest flattening in the repository, and the one that looks least like an N+1 in a
    template. `invoice.subscription.plan.name` reads like an attribute and costs two relation loads.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)

    row = viewmodels.invoice_list(session)["rows"][0]

    assert row["customer"] == "ana"
    assert row["plan"] == "pro"
    assert row["plan_price"] == "25.00"
    assert row["subscription_id"] == subscription_id


def test_money_is_formatted_here_and_not_in_the_template(session: SnakeSession) -> None:
    """Cents become money with two decimals, and never through a float.

    `4200 / 100` is `42.0` and happens to be right; `1 / 100` is `0.01` and is NOT the same value a
    `Decimal` gives. The conversion goes through `Decimal` so that the two agree at every amount,
    which on a page about money is the difference between a total and an approximation.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)

    row = viewmodels.invoice_list(session)["rows"][0]

    assert row["amount"] == "42.00"
    assert viewmodels.money_from_cents(1) == "0.01"
    assert viewmodels.money_from_cents(0) == "0.00"


def test_the_status_label_is_decided_here_and_not_in_two_templates(
    session: SnakeSession,
) -> None:
    """A settled invoice and an open one read differently, and the boolean still travels.

    Both, deliberately: the label is what a person reads and the boolean is what a template branches
    on to colour a row. Making the template derive one from the other is how two demos end up with
    two vocabularies for the same state.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    open_invoice = _invoice(session, subscription_id, 4200)
    settled = _invoice(session, subscription_id, 900)
    assert not isinstance(usecases.pay_invoice(session, settled.id, "card"), Failure)

    rows = {row["id"]: row for row in viewmodels.invoice_list(session)["rows"]}

    assert rows[open_invoice.id]["paid"] is False
    assert rows[open_invoice.id]["status_label"] == "Outstanding"
    assert rows[settled.id]["paid"] is True
    assert rows[settled.id]["status_label"] == "Settled"


# ---- The filter and the pager -----------------------------------------------------------------------


def test_the_settlement_filter_narrows_the_listing_and_comes_back(
    session: SnakeSession,
) -> None:
    """The filter reaches the WHERE, and the page says which filter it applied.

    It comes back as the STRING the form posted and not as the boolean it was parsed into, so the
    template marks the selected option without turning three values back into three cases.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)
    settled = _invoice(session, subscription_id, 900)
    assert not isinstance(usecases.pay_invoice(session, settled.id, "card"), Failure)

    everything = viewmodels.invoice_list(session)
    open_only = viewmodels.invoice_list(session, paid=viewmodels.OPEN_ONLY)
    paid_only = viewmodels.invoice_list(session, paid=viewmodels.PAID_ONLY)

    assert everything["total"] == 2
    assert everything["paid"] == viewmodels.PAID_ANY
    assert open_only["total"] == 1
    assert open_only["paid"] == viewmodels.OPEN_ONLY
    assert paid_only["total"] == 1
    assert [row["id"] for row in paid_only["rows"]] == [settled.id]


def test_a_filter_value_that_does_not_exist_is_no_filter_at_all(
    session: SnakeSession,
) -> None:
    """A typo in a hand-edited query string shows everything rather than raising.

    `paid=maybe` cannot be turned into a filter — a boolean has two values — so the alternatives are
    "show everything" or "500 on a mistyped URL", and the second is not a defensible answer. The
    value that comes back is the sanitised one, so the template never marks an option that is not in
    the list.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)

    page = viewmodels.invoice_list(session, paid="maybe")

    assert page["total"] == 1
    assert page["paid"] == viewmodels.PAID_ANY


def test_the_filter_offers_three_options_with_labels(session: SnakeSession) -> None:
    """Three options, each with the words a person reads, and NO query behind them."""
    page = viewmodels.invoice_list(session)

    assert [option["value"] for option in page["filters"]] == [
        viewmodels.PAID_ANY,
        viewmodels.PAID_ONLY,
        viewmodels.OPEN_ONLY,
    ]
    assert all(option["label"].strip() for option in page["filters"])


def test_the_middle_page_has_a_previous_and_a_next(session: SnakeSession) -> None:
    """The pager's arithmetic is done in the use case, and the page carries the answer."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    for _ in range(9):
        _invoice(session, subscription_id, 100)

    page = viewmodels.invoice_list(session, page=2, per_page=3)

    assert page["page"] == 2
    assert page["pages"] == 3
    assert page["total"] == 9
    assert page["has_prev"] and page["has_next"]
    assert page["prev_page"] == 1
    assert page["next_page"] == 3


def test_the_edges_do_not_offer_a_step_that_does_not_exist(
    session: SnakeSession,
) -> None:
    """`prev_page` and `next_page` are CLAMPED, so a template never links a page that is not there."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    for _ in range(4):
        _invoice(session, subscription_id, 100)

    first = viewmodels.invoice_list(session, page=1, per_page=2)
    last = viewmodels.invoice_list(session, page=2, per_page=2)

    assert (first["has_prev"], first["prev_page"]) == (False, 1)
    assert (last["has_next"], last["next_page"]) == (False, 2)


def test_a_page_past_the_end_lands_on_the_last_one(session: SnakeSession) -> None:
    """A stale bookmark is answered with the last page, not with an empty one nor a stack trace."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    for _ in range(3):
        _invoice(session, subscription_id, 100)

    page = viewmodels.invoice_list(session, page=99, per_page=2)

    assert page["page"] == 2
    assert len(page["rows"]) == 1


def test_an_empty_listing_is_still_one_page(session: SnakeSession) -> None:
    """Zero invoices is an answer: one page, no rows, and no division by zero on the way."""
    page = viewmodels.invoice_list(session, per_page=0)

    assert (page["page"], page["pages"], page["total"]) == (1, 1, 0)
    assert page["rows"] == []


# ---- The detail, and the sum that does not have to add up --------------------------------------------


def test_the_detail_carries_the_payments_oldest_first(session: SnakeSession) -> None:
    """The to-many of the page, in the order a ledger is read: what was paid, then what closed it."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    invoice = _invoice(session, subscription_id, 5000)
    _pay(session, invoice, 2000, "card")
    _pay(session, invoice, 3000, "transfer")

    page = viewmodels.invoice_detail(session, invoice.id)

    assert not isinstance(page, Failure)
    assert [payment["method"] for payment in page["payments"]] == ["card", "transfer"]
    assert page["payment_count"] == 2
    assert page["paid_total"] == "50.00"
    assert page["outstanding"] == "0.00"
    assert page["is_short"] is False


def test_an_invoice_flagged_settled_with_too_little_collected_says_so(
    session: SnakeSession,
) -> None:
    """THE reason this page exists: the flag and the payments can disagree, and nothing stops them.

    `paid` is a column and the payments are rows in another table; no constraint ties them together.
    So an invoice can say it is settled while half of it was ever collected, and that state survives
    every other page in the demos unnoticed. Here it is one subtraction and a boolean.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    invoice = _invoice(session, subscription_id, 5000)
    _pay(session, invoice, 2000, "card")
    invoice.paid = True
    session.update(invoice)
    session.commit()

    page = viewmodels.invoice_detail(session, invoice.id)

    assert not isinstance(page, Failure)
    assert page["paid_total"] == "20.00"
    assert page["outstanding"] == "30.00"
    assert page["is_short"] is True


def test_an_overpayment_leaves_nothing_outstanding_rather_than_a_debt(
    session: SnakeSession,
) -> None:
    """What is still owed is never negative: a refund is somebody else's page, not a negative total.

    Without the clamp the page would print `-10.00` under a heading that says "outstanding", which is
    a number a reader has to translate before it means anything.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    invoice = _invoice(session, subscription_id, 5000)
    _pay(session, invoice, 6000, "card")

    page = viewmodels.invoice_detail(session, invoice.id)

    assert not isinstance(page, Failure)
    assert page["outstanding"] == "0.00"


def test_an_invoice_that_does_not_exist_is_a_failure_and_not_an_empty_page(
    session: SnakeSession,
) -> None:
    """The `Failure` travels through UNCHANGED: mapping it to a 404 is the web layer's job."""
    page = viewmodels.invoice_detail(session, 4242)

    assert isinstance(page, Failure)
    assert page.reason == "not_found"


# ---- The report ---------------------------------------------------------------------------------------


def test_annotate_lists_every_plan_including_the_one_nobody_is_on(
    session: SnakeSession,
) -> None:
    """`annotate` keeps the plan with zero subscriptions, which a `GROUP BY` over them would drop.

    That row is the answer to "which tariffs are dead", and it is exactly the one the grouped query
    below cannot produce.
    """
    _account(session, username="ana", plan="pro", cents=2500)
    session.add(Plan(name="enterprise", price_cents=99_00))
    session.commit()

    page = viewmodels.billing_report(session, _LATER)
    counts = {row["name"]: row["subscription_count"] for row in page["plans"]}

    assert counts == {"pro": 1, "enterprise": 0}


def test_having_keeps_only_the_plans_that_have_billed_enough(
    session: SnakeSession,
) -> None:
    """The aggregate filtered by its own aggregate, and here the threshold IS the money.

    Safe on this side of the repository and unsafe on the other: billing counts integer CENTS, so
    `SUM(amount_cents) >= n` compares two integers on all three engines. `orders` stores a `NUMERIC`
    that SQLite keeps as text, which is why the orders report thresholds on a COUNT instead.
    """
    small = _account(session, username="ana", plan="starter", cents=500)
    big = _account(session, username="ben", plan="pro", cents=2500)
    _invoice(session, small, 300)
    _invoice(session, big, 9000)

    page = viewmodels.billing_report(session, _LATER, minimum_cents=1000)

    assert [row["plan"] for row in page["revenue"]] == ["pro"]
    assert page["revenue"][0]["invoice_count"] == 1
    assert page["revenue"][0]["revenue"] == "90.00"
    assert page["minimum"] == "10.00"


def test_a_plan_with_subscribers_and_no_revenue_is_named(session: SnakeSession) -> None:
    """The figure the report exists for: the gap between the roll call and the revenue.

    A plan somebody is subscribed to that has never invoiced anything is either a tariff nobody is
    being billed for or a billing job that stopped running. Neither is visible in either query alone,
    which is why the subtraction is done here instead of left to a reader comparing two tables.
    """
    _account(session, username="ana", plan="pro", cents=2500)
    # Ben is on `starter` and nobody has ever raised him an invoice: the silent plan of the fixture.
    _account(session, username="ben", plan="starter", cents=500)
    billed = _account(session, username="cleo", plan="team", cents=4000)
    _invoice(session, billed, 4000)
    session.add(Plan(name="enterprise", price_cents=99_00))
    session.commit()

    page = viewmodels.billing_report(session, _LATER)

    assert page["silent_plans"] == ["starter", "pro"]


def test_the_report_says_what_is_still_outstanding(session: SnakeSession) -> None:
    """The count and the total come from ONE statement, so they cannot belong to different moments."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _invoice(session, subscription_id, 4200)
    _invoice(session, subscription_id, 800)
    settled = _invoice(session, subscription_id, 900)
    assert not isinstance(usecases.pay_invoice(session, settled.id, "card"), Failure)

    page = viewmodels.billing_report(session, _LATER)

    assert page["unpaid_count"] == 2
    assert page["unpaid_total"] == "50.00"


def test_a_company_with_no_invoices_reports_zero_and_not_none(
    session: SnakeSession,
) -> None:
    """`SUM` over no rows is `NULL` in SQL, and a page cannot print `NULL`.

    It is turned into a zero in the selector, where the decision can be argued, rather than in a
    template that would print the word "None" into the page.
    """
    page = viewmodels.billing_report(session, _LATER)

    assert page["unpaid_count"] == 0
    assert page["unpaid_total"] == "0.00"
    assert page["revenue"] == []


# ---- The query budget ----------------------------------------------------------------------------------


def test_the_list_page_is_two_statements(session: SnakeSession) -> None:
    """TWO, as a literal: the count and the page of rows. There is no third.

    The pilot's listing costs three because its filter is a TABLE of warehouses that has to be read.
    This filter is a boolean, so its three options are a Python constant — the same statement the
    orders listing saves for the same reason, one domain over.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    for _ in range(5):
        _invoice(session, subscription_id, 100)

    with capture_queries() as collector:
        page = viewmodels.invoice_list(session)

    assert len(page["rows"]) == 5
    assert collector.report().count == 2, collector.report().to_text()


def test_the_list_page_costs_the_same_at_three_invoices_and_at_thirty(
    make_session: Callable[[], SnakeSession],
) -> None:
    """The N+1 net, and the one that matters most here: THREE hops are flattened per row.

    Two databases and not two pages of one, because the second measurement has to start clean. And
    the assertion is one count against the OTHER count rather than a literal: what must never change
    is the SLOPE. A template reaching for `invoice.subscription.plan.name` would make this page cost
    two extra queries per row and nothing else in the suite would notice.
    """

    def cost(session: SnakeSession, invoices: int) -> int:
        subscription_id = _account(session, username="ana", plan="pro", cents=2500)
        for _ in range(invoices):
            _invoice(session, subscription_id, 100)
        with capture_queries() as collector:
            page = viewmodels.invoice_list(session, per_page=invoices + 1)
        assert len(page["rows"]) == invoices, (
            "the budget was measured over the wrong page"
        )
        return collector.report().count

    small, large = make_session(), make_session()
    try:
        assert cost(small, 3) == cost(large, 30)
    finally:
        small.close()
        large.close()


def test_the_detail_page_is_two_statements(session: SnakeSession) -> None:
    """TWO, as a literal: the invoice with its three-deep chain, and its payments.

    The chain is one statement because all three hops are to-one and travel as LEFT JOINs on the same
    SELECT. The payments are the second because they are a to-many, which is a select-in and cannot
    be anything else without multiplying the invoice row.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    invoice = _invoice(session, subscription_id, 5000)
    _pay(session, invoice, 2000, "card")

    with capture_queries() as collector:
        page = viewmodels.invoice_detail(session, invoice.id)

    assert not isinstance(page, Failure)
    assert collector.report().count == 2, collector.report().to_text()


def test_the_detail_page_costs_the_same_at_one_payment_and_at_twenty(
    make_session: Callable[[], SnakeSession],
) -> None:
    """The to-many is ONE extra statement, however many payments come back."""

    def cost(session: SnakeSession, payments: int) -> int:
        subscription_id = _account(session, username="ana", plan="pro", cents=2500)
        invoice = _invoice(session, subscription_id, 100_000)
        # The kinds cycle instead of being invented. `method-0` used to go in, because the column
        # was a `str` and any string was a payment method; now the set is CLOSED, which is the whole
        # point of the discriminator, and this loop is where that stopped being an abstraction.
        kinds = list(PAYMENT_KINDS)
        for index in range(payments):
            _pay(session, invoice, 100, kinds[index % len(kinds)])
        with capture_queries() as collector:
            page = viewmodels.invoice_detail(session, invoice.id)
        assert not isinstance(page, Failure)
        assert page["payment_count"] == payments
        return collector.report().count

    small, large = make_session(), make_session()
    try:
        assert cost(small, 1) == cost(large, 20)
    finally:
        small.close()
        large.close()


def test_the_report_is_four_statements(session: SnakeSession) -> None:
    """FOUR, as a literal, and every one accounted for.

    The `annotate` over the plans, the `GROUP BY` + `HAVING` over the invoices, the one projection
    that answers "how many are open and how much is that" in a single row, and the ageing table. The
    third is one statement and not two on purpose: two round trips for two halves of one sentence can
    be measured a moment apart, and on a page about money two numbers that do not belong to each
    other are worse than one number missing.

    THE FOURTH IS THE ONE WORTH READING, because everything it carries could have been two or three
    statements or a loop. It projects the due date —`issued_at + 30 days`, computed by the engine—
    and the share of each debt that has been collected, which is a correlated `SUM` over the payments
    of that invoice. Asking for the payments separately would be a round trip per row: the N+1 this
    whole layer exists to refuse, wearing the clothes of a perfectly ordinary report.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    for _ in range(4):
        _invoice(session, subscription_id, 100)

    with capture_queries() as collector:
        viewmodels.billing_report(session, _LATER)

    assert collector.report().count == 4, collector.report().to_text()


def test_the_report_costs_the_same_at_one_plan_and_at_twenty(
    make_session: Callable[[], SnakeSession],
) -> None:
    """Flat: every statement on the report is an aggregate over a whole table."""

    def cost(session: SnakeSession, plans: int) -> int:
        for index in range(plans):
            subscription_id = _account(
                session, username=f"user{index}", plan=f"plan-{index}", cents=100
            )
            _invoice(session, subscription_id, 500)
        with capture_queries() as collector:
            page = viewmodels.billing_report(session, _LATER)
        assert len(page["plans"]) == plans
        return collector.report().count

    small, large = make_session(), make_session()
    try:
        assert cost(small, 1) == cost(large, 20)
    finally:
        small.close()
        large.close()


def _issue_on(
    session: SnakeSession, subscription_id: int, cents: int, when: SnakeUtc
) -> Invoice:
    """An invoice raised on a GIVEN day: the ageing section is about how old a debt is."""
    invoice = usecases.issue_invoice(session, subscription_id, cents)
    invoice.issued_at = when
    session.update(invoice)
    session.commit()
    return invoice


def test_the_due_date_is_the_issue_date_plus_the_term_and_the_engine_computes_it(
    session: SnakeSession,
) -> None:
    """`issued_at + 30 days`, added by the DATABASE and not by Python.

    Thirty DAYS and not one month, and that is not a rounding of the domain: "net 30" is counted in
    days in the real world, and it is also the only unit the three engines agree on. SQLite overflows
    a month —2026-01-31 plus one month is 2026-03-03 there and 2026-02-28 on the other two, which is
    `Cap.CALENDAR_INTERVAL`— so a report in months would print different figures depending on which
    engine the reader happened to be running.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _issue_on(session, subscription_id, 2500, SnakeUtc(2024, 1, 10, 9, 0))

    page = viewmodels.billing_report(session, cutoff=SnakeUtc(2024, 6, 1, 0, 0))

    assert [row["due"] for row in page["overdue"]] == ["2024-02-09"]


def test_the_collected_fraction_is_a_real_division_and_not_an_integer_one(
    session: SnakeSession,
) -> None:
    """500 collected out of 2500 is a fifth, and an integer division would call it nothing.

    THIS IS THE WHOLE REASON `snake_cast` EXISTS. Both columns are integer cents, so `collected /
    amount` is integer division on PostgreSQL and SQLite and comes back `0` — the same class of
    silent wrong answer the ORM already declares for `45/50`. The cast is what makes the figure mean
    what it looks like.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    invoice = _issue_on(session, subscription_id, 2500, SnakeUtc(2024, 1, 10, 9, 0))
    _pay(session, invoice, 500, "card")

    page = viewmodels.billing_report(session, cutoff=SnakeUtc(2024, 6, 1, 0, 0))

    assert [row["collected"] for row in page["overdue"]] == ["20.0%"]


def test_an_invoice_nobody_has_paid_reads_zero_rather_than_nothing(
    session: SnakeSession,
) -> None:
    """`SUM` over no payments is NULL, and NULL is not an answer a debt page can print.

    The zero is put in with `snake_coalesce` INSIDE the statement rather than in Python afterwards,
    which is the same call `unpaid_total` argues for a few figures up: a page about money says a
    number, and "no payments" means nothing has been collected — not that it is unknown.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _issue_on(session, subscription_id, 2500, SnakeUtc(2024, 1, 10, 9, 0))

    page = viewmodels.billing_report(session, cutoff=SnakeUtc(2024, 6, 1, 0, 0))

    assert [row["collected"] for row in page["overdue"]] == ["0.0%"]


def test_only_the_debts_older_than_the_cutoff_are_listed(session: SnakeSession) -> None:
    """The FILTER compares the issue date against a cutoff, not the shifted due date against now.

    Two reasons, and the first one is the one a DBA would give: `issued_at < cutoff` can use an index
    on `issued_at`, while `issued_at + 30 days < now` has to be computed for every row before
    anything can be discarded. Shifting a column is for producing a VALUE somebody reads.

    The second is measured. A `SnakeUtc` is ISO-8601 TEXT in SQLite and its date functions hand the
    result back WITHOUT the offset, so comparing a shifted timestamp against a bound one is a
    lexicographic comparison between two differently-shaped strings. It happens to work; it is not
    something to build a filter on.

    The cutoff itself touches no column, which is exactly why it belongs in Python.
    """
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    _issue_on(session, subscription_id, 1000, SnakeUtc(2024, 1, 10, 9, 0))
    _issue_on(session, subscription_id, 2000, SnakeUtc(2024, 5, 30, 9, 0))

    page = viewmodels.billing_report(session, cutoff=SnakeUtc(2024, 3, 1, 0, 0))

    assert [row["amount"] for row in page["overdue"]] == ["10.00"]


def test_a_settled_invoice_never_appears_however_old_it_is(
    session: SnakeSession,
) -> None:
    """An old debt that was paid is not a debt. The section is about what is still owed."""
    subscription_id = _account(session, username="ana", plan="pro", cents=2500)
    invoice = _issue_on(session, subscription_id, 1000, SnakeUtc(2024, 1, 10, 9, 0))
    usecases.pay_invoice(session, invoice.id, "card")

    page = viewmodels.billing_report(session, cutoff=SnakeUtc(2024, 6, 1, 0, 0))

    assert page["overdue"] == []
