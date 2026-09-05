"""billing domain — SELECTORS: plans, a user's subscriptions, invoices, payments and the money report.

Every framework re-exports them from `apps/billing/selectors.py`.

The domain gets THREE pages and not five, and the plan says which: list, detail and report. There is
no `create`, no `update` and no `delete`, because an invoice is not a row somebody edits — it is
raised by an operation and settled by another, and a form that let a person retype an amount would be
a demo of the one thing accounting software must never offer. What billing is here to show is the
READ side of money: a listing that reaches three tables deep without an N+1, and a report made of
aggregates a `filter` cannot answer.

Every read here comes in TWO pieces, and the split is the seam the asynchronous demo stands on. The
FRAGMENT builds a `SnakeQuery` (or, for `select`/`annotate`, the query PLUS the columns/aggregates it
projects) and does not run it; the EXECUTOR takes a session and runs it. Only the executor has a
colour — `session.all(...)` on one path, `await session.all(...)` on the other — so the SQL, which is
the part that drifts when it is written twice, is written once. `select` takes its columns
POSITIONALLY and `annotate` its aggregates as a MAPPING, so the two kinds of read expose their shared
half differently — a tuple-returning function for the first, a dict-returning one for the second —
but the rule is the same one `accounts_selectors`/`taxonomy_selectors` already follow: the expression
is written ONCE, and both colours consume the same object. See `shared/aio/billing_usecases.py` for
the other half.
"""

from __future__ import annotations

from snakeorm import (
    SnakeDatePart,
    SnakeQuery,
    SnakeSession,
    SnakeUtc,
    SnakeValue,
    count,
    snake_cast,
    snake_coalesce,
    snake_date_add,
    sum_,
)

from shared.models import Invoice, Payment, Plan, PlanStats, Subscription


def plans_query() -> SnakeQuery[Plan]:
    """FRAGMENT: every plan, by price. NOT executed."""
    return SnakeQuery(Plan).order_by(Plan.price_cents.asc())


def list_plans(session: SnakeSession) -> list[Plan]:
    """Every plan, by price."""
    return session.all(plans_query())


def subscriptions_of(user_id: int) -> SnakeQuery[Subscription]:
    """FRAGMENT: a user's subscriptions, with their plan loaded. NOT executed."""
    return (
        SnakeQuery(Subscription)
        .filter(Subscription.user_id == user_id)
        .include(Subscription.plan)
        .order_by(Subscription.id.asc())
    )


def subscriptions_of_user(session: SnakeSession, user_id: int) -> list[Subscription]:
    """A user's subscriptions, with their plan loaded."""
    return session.all(subscriptions_of(user_id))


def invoices_of(subscription_id: int) -> SnakeQuery[Invoice]:
    """FRAGMENT: a subscription's invoices, most recent first. NOT executed."""
    return (
        SnakeQuery(Invoice)
        .filter(Invoice.subscription_id == subscription_id)
        .order_by(Invoice.issued_at.desc())
    )


def invoices_of_subscription(
    session: SnakeSession, subscription_id: int
) -> list[Invoice]:
    """A subscription's invoices, most recent first."""
    return session.all(invoices_of(subscription_id))


def invoices_of_customer(user_id: int) -> SnakeQuery[Invoice]:
    """FRAGMENT: every invoice of a CUSTOMER, across all their subscriptions. NOT executed.

    `Invoice.subscription.user_id` is a two-hop navigation and the emitter plans it as a JOIN inside
    ONE statement. The alternative is asking per subscription — a round trip to list them and one
    more each — which is invisible on a customer with two and an N+1 on anybody real.
    """
    return (
        SnakeQuery(Invoice)
        .filter(Invoice.subscription.user_id == user_id)
        .order_by(Invoice.issued_at.desc())
    )


def customer_invoices(session: SnakeSession, user_id: int) -> list[Invoice]:
    """Every invoice of a customer, most recent first."""
    return session.all(invoices_of_customer(user_id))


def subscription_by_id(subscription_id: int) -> SnakeQuery[Subscription]:
    """FRAGMENT: one subscription by id. NOT executed.

    It lives here and not only inline in `cancel_subscription` because that service does the SAME
    look-up before it writes: a cancellation is "find the subscription, flip it inactive", and the
    finding half is this. The asynchronous twin of that service has to find it with the very same
    `WHERE` and not with a second one that happens to look alike today.
    """
    return SnakeQuery(Subscription).filter(Subscription.id == subscription_id)


def get_subscription(
    session: SnakeSession, subscription_id: int
) -> Subscription | None:
    """One subscription by id, or `None`.

    It exists because `settle` has to check WHOSE subscription it is about to bill: an order pointing
    at an invoice raised against somebody else's subscription is a graph no report can add up, and
    nothing in the schema forbids it. Looking the row up is what turns that into a refusal the page
    can explain instead of money quietly landing on the wrong person.
    """
    return session.first(subscription_by_id(subscription_id))


def invoice_by_id(invoice_id: int) -> SnakeQuery[Invoice]:
    """FRAGMENT: one invoice by id, bare (no relations loaded). NOT executed.

    The look-up `pay_invoice` needs before it writes: collecting an invoice is "find it, add the
    payment, mark it paid", and the finding half is this — the SAME `WHERE` a `not_found` on a stale
    id from a form has to answer on both colours.
    """
    return SnakeQuery(Invoice).filter(Invoice.id == invoice_id)


def get_invoice(session: SnakeSession, invoice_id: int) -> Invoice | None:
    """One invoice by id, or `None`.

    It exists because `orders` bills against an invoice and has to be able to say `not_found`
    for a stale id from a form. Without it the id travelled straight into a foreign key and the
    answer to a mistyped number was a driver error raised inside a commit.
    """
    return session.first(invoice_by_id(invoice_id))


def unpaid_invoices_query() -> SnakeQuery[Invoice]:
    """FRAGMENT: every unpaid invoice (for collection), oldest first. NOT executed."""
    return (
        SnakeQuery(Invoice)
        # `== False`, not `not Invoice.paid`: here `__eq__` does NOT return a bool, it returns a
        # SnakeCondition that gets emitted as SQL. E712's "fix" would evaluate the descriptor's
        # truthiness in Python and the filter would vanish from the query, in silence.
        .filter(Invoice.paid == False)  # noqa: E712
        .order_by(Invoice.issued_at.asc())
    )


def unpaid_invoices(session: SnakeSession) -> list[Invoice]:
    """Every unpaid invoice (for collection)."""
    return session.all(unpaid_invoices_query())


def invoice_listing(*, paid: bool | None = None) -> SnakeQuery[Invoice]:
    """FRAGMENT: the invoice listing, most recent first, optionally narrowed by settlement. NOT run.

    Not executed and carrying no `limit`, because the page consumes it twice — once counted and once
    fetched — and the pager's total has to be the total of the rows on screen. The third time the
    same paragraph is written in this repository, and the third time for the same measured reason.

    `issued_at` with the id as the tiebreaker: the seeder spreads the dates over the history and two
    invoices raised in the same second are ordinary, so the date alone is not a stable order under
    LIMIT/OFFSET — it shows one row twice and skips another.
    """
    query = SnakeQuery(Invoice).order_by(Invoice.issued_at.desc(), Invoice.id.desc())
    if paid is not None:
        # `== paid` and not `is paid`: `__eq__` on a column builds a SQL condition, and Python's
        # identity operator would evaluate the descriptor's truthiness and drop the filter silently.
        query = query.filter(Invoice.paid == paid)
    return query


def with_parties(query: SnakeQuery[Invoice]) -> SnakeQuery[Invoice]:
    """FRAGMENT: loads the chain an invoice page always shows — subscription, its plan, its user.

    THREE hops deep and all to-one, so all three are LEFT JOINs on the SAME statement: the page costs
    one query whether it lists three invoices or three hundred. `Invoice.subscription.user` is the
    two-step navigation this repository otherwise only exercises in the orders export, and it is
    where the plan's "no relation navigation left for a template" earns its keep — the alternative is
    `invoice.subscription.plan.name` inside a loop, in the layer no `assert_queries` watches.

    A fragment and not part of `invoice_listing` because the COUNT does not want it: three needless
    LEFT JOINs give the same number, more slowly.
    """
    return query.include(Invoice.subscription.plan, Invoice.subscription.user)


def count_invoices(session: SnakeSession, *, paid: bool | None = None) -> int:
    """How many invoices the listing has, for the pager. `COUNT(*)` over the SAME fragment."""
    return session.count(invoice_listing(paid=paid))


def invoices_page(
    session: SnakeSession,
    *,
    paid: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Invoice]:
    """One page of invoices with the whole chain loaded: ONE statement, whatever the page size."""
    return session.all(
        with_parties(invoice_listing(paid=paid)).limit(limit).offset(offset)
    )


def invoice_with_parties_by_id(invoice_id: int) -> SnakeQuery[Invoice]:
    """FRAGMENT: one invoice WITH its subscription, plan and user loaded. NOT executed."""
    return with_parties(SnakeQuery(Invoice)).filter(Invoice.id == invoice_id)


def get_invoice_with_parties(session: SnakeSession, invoice_id: int) -> Invoice | None:
    """One invoice WITH its subscription, plan and user already loaded, or `None`.

    The bare `get_invoice` above is what a WRITE path wants — the row, not the rows it points at.
    This is what a PAGE wants, and the difference is a whole class of bug: a template printing
    `invoice.subscription.user.username` off the bare row fires two queries while it renders.
    """
    return session.first(invoice_with_parties_by_id(invoice_id))


def payments_of_invoice(invoice_id: int) -> SnakeQuery[Payment]:
    """FRAGMENT: the payments against one invoice, oldest first. NOT executed.

    Oldest first and not newest first, unlike every listing in this repository, because a payment
    history is read as a story: what was paid, then what was still owed, then what closed it. A
    reversed ledger is a ledger you have to read backwards to add up.
    """
    return (
        SnakeQuery(Payment)
        .filter(Payment.invoice_id == invoice_id)
        .order_by(Payment.paid_at.asc(), Payment.id.asc())
    )


def payments_of(session: SnakeSession, invoice_id: int) -> list[Payment]:
    """The payments against one invoice, oldest first: the to-many the detail page shows."""
    return session.all(payments_of_invoice(invoice_id))


def plan_stats_query() -> SnakeQuery[Plan]:
    """FRAGMENT: every plan by price, NOT executed — `annotate` stacks the aggregate on top."""
    return SnakeQuery(Plan).order_by(Plan.price_cents.asc())


def plan_stats_aggregates() -> dict[str, SnakeValue[int]]:
    """FRAGMENT: the aggregate mapping `plan_stats` annotates onto `PlanStats`.

    `annotate` takes its aggregates as `**kwargs`, not positionally, so the shared half of this read
    is a dict and not a tuple like `revenue_by_plan_columns` below — same rule (write the expression
    once), the shape that matches how the session actually consumes it.
    """
    return {"subscription_count": Plan.subscriptions.count()}


def plan_stats(session: SnakeSession) -> list[PlanStats]:
    """Every plan with how many subscriptions it has, typed, in ONE statement.

    A correlated aggregate over the inverse side projected into `PlanStats`: no dict of `object`, and
    no second query per plan. A plan nobody subscribes to still comes back, with a zero — which is
    the half a `GROUP BY` over the subscriptions would lose, and exactly the row a "which tariffs are
    dead" question is about.
    """
    return session.annotate(plan_stats_query(), PlanStats, **plan_stats_aggregates())


def revenue_by_plan_query(*, minimum_cents: int = 1) -> SnakeQuery[Invoice]:
    """FRAGMENT: invoices grouped by plan, kept only above the `HAVING` threshold. NOT executed.

    Two hops in the GROUP BY (`invoice -> subscription -> plan`), which the emitter plans as JOINs
    inside the one statement. Grouping by the plan id and fetching the names afterwards would be the
    same report with an N+1 bolted to it.
    """
    return (
        SnakeQuery(Invoice)
        .group_by(Invoice.subscription.plan.name)
        .having(sum_(Invoice.amount_cents) >= minimum_cents)
        .order_by(Invoice.subscription.plan.name.asc())
    )


def revenue_by_plan_columns() -> tuple[
    SnakeValue[str], SnakeValue[int], SnakeValue[int | None]
]:
    """FRAGMENT: the three columns `revenue_by_plan` projects (name, count, sum).

    `select` takes its columns POSITIONALLY, so the shared half is a TUPLE — unpacked at the call
    site into three names rather than starred into `select`, which is what keeps each column typed
    (`str`, `int`, `int | None`) instead of falling through to `select`'s untyped `*columns` overload.
    """
    return (Invoice.subscription.plan.name, count(), sum_(Invoice.amount_cents))


def revenue_by_plan(
    session: SnakeSession, *, minimum_cents: int = 1
) -> list[tuple[str, int, int]]:
    """Invoiced money per plan, only for the plans that have invoiced at least `minimum_cents`. GROUP BY + HAVING.

    The aggregate filtered by its own aggregate, and here the threshold IS the money — which the
    orders report deliberately avoids. It is safe here and unsafe there because of how the two
    domains store money: `billing` counts integer CENTS and `orders` stores a `NUMERIC`, and a
    `Decimal` is the type SQLite keeps as text and sums into a float. `SUM(amount_cents) >= n`
    compares two integers on all three engines, so this page answers the same question everywhere.

    The plans that have never invoiced anything DROP OUT, and that is the point of the `HAVING`
    rather than a flaw in it: `plan_stats` above is the roll call, and this is the revenue. Reading
    them side by side is what shows a plan with subscribers and no invoices, which is a billing bug
    worth seeing.
    """
    name_col, count_col, sum_col = revenue_by_plan_columns()
    rows = session.select(
        revenue_by_plan_query(minimum_cents=minimum_cents), name_col, count_col, sum_col
    )
    return [(name, int(issued), int(cents or 0)) for name, issued, cents in rows]


def open_invoices_query() -> SnakeQuery[Invoice]:
    """FRAGMENT: every unpaid invoice, with NO `ORDER BY`. NOT executed.

    It is a different query from `unpaid_invoices_query` above and not the same one reused, and the
    reason is not tidiness: a projection of pure aggregates ordered by a column that is in no GROUP BY
    is rejected outright by Postgres. `unpaid_invoices_query` carries an `ORDER BY issued_at` for a
    listing; `unpaid_total` has one row and nothing to order.
    """
    return SnakeQuery(Invoice).filter(Invoice.paid == False)  # noqa: E712


def unpaid_total_columns() -> tuple[SnakeValue[int], SnakeValue[int | None]]:
    """FRAGMENT: the COUNT and SUM `unpaid_total` projects together, in the SAME statement.

    Two calls would be two round trips answering halves of one sentence, and the halves could be
    measured a moment apart — which on a page about money is the difference between "six invoices,
    134 euros" and a pair of numbers that do not belong to each other.
    """
    return (count(), sum_(Invoice.amount_cents))


def unpaid_total(session: SnakeSession) -> tuple[int, int]:
    """How many invoices are still open and how much they add up to, in ONE statement.

    `SUM` over no rows is `NULL`, not zero, and that is SQL rather than a quirk of an engine: the sum
    of an empty set has no value. The page needs a number, so the `None` is turned into zero HERE,
    where the decision can be argued, instead of in a template that would print the word "None".
    """
    count_col, sum_col = unpaid_total_columns()
    rows = session.select(open_invoices_query(), count_col, sum_col)
    if not rows:
        return (0, 0)
    open_count, cents = rows[0]
    return (int(open_count), int(cents or 0))


# What a customer is given to pay before the debt counts as late. THIRTY DAYS and not one month, and
# the unit is the decision rather than the number: "net 30" is counted in days everywhere it is
# written, and it is also the only unit the three engines agree on. SQLite OVERFLOWS a calendar month
# —2026-01-31 plus one month is 2026-03-03 there and 2026-02-28 on the other two, which is what
# `Cap.CALENDAR_INTERVAL` declares— so a report in months would print a different due date depending
# on which engine the reader happened to be running.
INVOICE_TERM_DAYS = 30


def due_date() -> SnakeValue[SnakeUtc]:
    """FRAGMENT: when an invoice has to be paid by — `issued_at + 30 days`. NOT executed.

    Computed by the ENGINE and not in Python, which is the point of it being here: the same value can
    then be ordered by, compared against and projected without the rows ever leaving the database.
    Each engine spells the shift its own way (`+ INTERVAL`, `DATE_ADD`, a modifier string) and the
    dialect is what knows which.
    """
    return snake_date_add(Invoice.issued_at, INVOICE_TERM_DAYS, SnakeDatePart.DAY)


def collected_fraction() -> SnakeValue[float]:
    """FRAGMENT: how much of an invoice has actually been paid, as a REAL fraction. NOT executed.

    THE CAST IS THE WHOLE POINT. Both sides are integer cents, so `collected / amount` is integer
    division on PostgreSQL and SQLite and answers `0` for every invoice that is not fully paid —
    the same silent wrong answer the ORM declares for `45/50`, and worse here because a page about
    money would show it as a fact.

    The `COALESCE` comes FIRST and is not interchangeable with the cast: `SUM` over no payments is
    NULL on every engine, and an invoice nobody has paid has collected zero rather than an unknown
    amount. Putting the zero in inside the statement is also what keeps the result non-nullable, so
    the division is a plain `float` and the page never has to print the word "None".

    The divisor cannot be zero here: `overdue_query` keeps only invoices with an amount, which is a
    statement about the DOMAIN —a debt of nothing is not a debt— rather than a guard bolted on.
    """
    collected = snake_coalesce(Invoice.payments.sum_(Payment.amount_cents), 0)
    return snake_cast(collected, float) / snake_cast(Invoice.amount_cents, float)


def overdue_query(cutoff: SnakeUtc, *, limit: int = 10) -> SnakeQuery[Invoice]:
    """FRAGMENT: the oldest debts still open on `cutoff`, bounded. NOT executed.

    THE FILTER COMPARES THE ISSUE DATE, not the shifted due date, and that is deliberate twice over.
    A DBA would give the first reason: `issued_at < cutoff` can use an index on `issued_at`, while
    `issued_at + 30 days < now` has to be computed for every row before anything can be discarded.
    Shifting a column is for producing a VALUE somebody reads.

    The second is measured. A `SnakeUtc` is ISO-8601 TEXT in SQLite and its date functions give the
    result back WITHOUT the offset, so comparing a shifted timestamp against a bound one puts two
    differently-shaped strings side by side. It happens to answer correctly; it is not a thing to
    build a filter on.

    `cutoff` is passed in rather than read from the clock here, for the same reason the rest of this
    module takes its bounds as parameters: a fragment that asked the time would answer differently on
    two runs and could not be tested.
    """
    return (
        SnakeQuery(Invoice)
        .filter(
            Invoice.paid == False,  # noqa: E712
            Invoice.amount_cents > 0,
            Invoice.issued_at < cutoff,
        )
        .order_by(Invoice.issued_at.asc(), Invoice.id.asc())
        .limit(limit)
    )


def overdue_columns() -> tuple[
    SnakeValue[int], SnakeValue[int], SnakeValue[SnakeUtc], SnakeValue[float]
]:
    """FRAGMENT: the four values the ageing table projects, in ONE statement.

    The due date and the collected fraction travel WITH the invoice they belong to. Asking for them
    separately would be one round trip per figure over the same rows, and on a page about money two
    numbers measured a moment apart are worse than one number missing — the argument
    `unpaid_total_columns` already makes a few figures up.
    """
    return (Invoice.id, Invoice.amount_cents, due_date(), collected_fraction())


def overdue_ageing(
    session: SnakeSession, cutoff: SnakeUtc, *, limit: int = 10
) -> list[tuple[int, int, SnakeUtc, float]]:
    """The oldest open debts, each with its due date and how much of it has been collected."""
    id_col, amount_col, due_col, collected_col = overdue_columns()
    return session.select(
        overdue_query(cutoff, limit=limit), id_col, amount_col, due_col, collected_col
    )
