"""billing domain use cases (plans, subscriptions, invoices), written once.

`pay_invoice` is the compound case: it creates the `Payment` AND marks the invoice paid in the same
unit of work (the service makes it atomic; the use case commits). `not_found` if the invoice is gone.

The three READ cases at the bottom are what the domain's SSR pages go through — list, detail and
report, the three the plan gives billing and no more. They follow the shape `inventory` set as the
pilot: the pager's arithmetic lives HERE, because how many pages there are depends on how many rows
there are and only this layer knows that; and both numbers that arrive from a URL get clamped,
because `per_page=0` is a division by zero and `page=99` is a stale bookmark, and neither of those is
a stack trace.
"""

from __future__ import annotations

from dataclasses import dataclass

from snakeorm import SnakeSession, SnakeUtc

from shared.models import Invoice, Payment, Plan, PlanStats, Subscription
from shared.selectors import billing_selectors as selectors
from shared.services import billing_services as services
from shared.usecases.result import Failure


def list_plans(session: SnakeSession) -> list[Plan]:
    """Every available plan."""
    return selectors.list_plans(session)


def subscriptions_of_user(session: SnakeSession, user_id: int) -> list[Subscription]:
    """A user's subscriptions, with their plan loaded."""
    return selectors.subscriptions_of_user(session, user_id)


def invoices_of_subscription(
    session: SnakeSession, subscription_id: int
) -> list[Invoice]:
    """A subscription's invoices."""
    return selectors.invoices_of_subscription(session, subscription_id)


def invoices_of_customer(session: SnakeSession, user_id: int) -> list[Invoice]:
    """Every invoice of a customer, across all their subscriptions, in ONE statement.

    The one above answers for a subscription; asking it per subscription is the N+1 this replaces.
    """
    return selectors.customer_invoices(session, user_id)


def unpaid_invoices(session: SnakeSession) -> list[Invoice]:
    """Every invoice still awaiting payment (for the collector)."""
    return selectors.unpaid_invoices(session)


def subscribe(session: SnakeSession, user_id: int, plan_id: int) -> Subscription:
    """Signs a user up to a plan and commits the subscription."""
    subscription = services.subscribe(session, user_id, plan_id)
    session.commit()
    return subscription


def cancel_subscription(session: SnakeSession, subscription_id: int) -> None | Failure:
    """Cancels a subscription; `not_found` if it does not exist."""
    if not services.cancel_subscription(session, subscription_id):
        return Failure("not_found")
    session.commit()
    return None


def issue_invoice(
    session: SnakeSession, subscription_id: int, amount_cents: int
) -> Invoice:
    """Issues an invoice for a subscription and commits it."""
    invoice = services.issue_invoice(session, subscription_id, amount_cents)
    session.commit()
    return invoice


def pay_invoice(
    session: SnakeSession, invoice_id: int, method: str, **details: str
) -> Payment | Failure:
    """Collects an invoice (creates the payment and marks it paid); `not_found` if the invoice is gone.

    A form posts `method=card`, so a word has to become a KIND, and the two ways it can fail are
    told apart: `unknown_method` is a word nobody declared, `not_found` is an invoice that is gone.
    Before, any string went in — `crypto`, `carrd` and the empty string were all stored, and the row
    looked exactly as valid as the others.
    """
    if method not in services.PAYMENT_KINDS:
        return Failure("unknown_method")
    payment = services.pay_invoice(session, invoice_id, method, **details)
    if payment is None:
        return Failure("not_found")
    session.commit()
    return payment


@dataclass(frozen=True, slots=True)
class InvoicePage:
    """One page of invoices with everything the pager needs to draw itself.

    The four travel together because they are ONE answer, which is the lesson `inventory`'s
    `StockPage` wrote down first: handing back only the rows makes the caller ask for the total
    separately, and the caller that asks separately is the one that filters the two questions
    differently — a pager saying "47 invoices" over a listing that shows a different 47.

    `page` is the CLAMPED page, which is the whole reason it comes back at all: the number arrives
    from a URL, so it is whatever somebody typed there.
    """

    rows: list[Invoice]
    total: int
    page: int
    pages: int


def paginate_invoices(
    session: SnakeSession,
    *,
    paid: bool | None = None,
    page: int = 1,
    per_page: int = 20,
) -> InvoicePage:
    """A page of invoices, optionally narrowed to the settled or the open ones. TWO statements.

    Two and not three, and the reason is the same one that makes the orders listing cheaper than the
    stock listing: this filter is a BOOLEAN, so its options are a Python constant and there is no
    table of them to read. The pilot filters by a table of warehouses and pays a third statement for
    it.

    An unknown filter is impossible here —a boolean has two values and `None` means "no filter"— so
    there is no equivalent of the pilot's "empty page rather than `not_found`" decision to make.
    """
    per_page = max(1, per_page)
    total = selectors.count_invoices(session, paid=paid)
    pages = max(1, -(-total // per_page))
    page = min(max(1, page), pages)
    rows = selectors.invoices_page(
        session, paid=paid, limit=per_page, offset=(page - 1) * per_page
    )
    return InvoicePage(rows=rows, total=total, page=page, pages=pages)


def show_invoice(session: SnakeSession, invoice_id: int) -> Invoice | Failure:
    """One invoice with its subscription, plan and user loaded; `not_found` if it is gone.

    It is a different function from `get_invoice` in the selectors and from the bare lookup `settle`
    uses, and the difference is the same one the other two domains draw: a WRITE path wants the row,
    a PAGE wants the rows it points at. Serving both from one function means either a page that
    fires two queries while it renders or an operation that pays for a plan name it never reads.
    """
    invoice = selectors.get_invoice_with_parties(session, invoice_id)
    return invoice if invoice is not None else Failure("not_found")


def payments_of(session: SnakeSession, invoice_id: int) -> list[Payment]:
    """The payments against an invoice, WITHOUT checking that the invoice exists.

    The caller that needs the difference — the detail page — has already fetched the invoice and
    already got its `not_found`. Asking again here would be a third statement on every visit to
    learn what the caller already knows, which is the call `inventory_usecases.stock_history` makes
    for the same reason.
    """
    return selectors.payments_of(session, invoice_id)


@dataclass(frozen=True, slots=True)
class BillingReport:
    """The three figures the money report is made of: the roll call, the revenue and what is open.

    `plans` is `annotate` and `revenue` is `GROUP BY` + `HAVING`, and reading them side by side is
    the point: a plan appears in the first with subscribers and is missing from the second when it
    has never invoiced anything, which is a billing bug the two queries only reveal together.

    `unpaid_count` and `unpaid_cents` are one statement and travel as a pair, because two round trips
    for two halves of one sentence can be measured a moment apart — and on a page about money, two
    numbers that do not belong to each other is worse than one number missing.
    """

    plans: list[PlanStats]
    revenue: list[tuple[str, int, int]]
    unpaid_count: int
    unpaid_cents: int
    # The oldest debts still open, each with the date it was due and the share of it that has
    # been collected. Bounded, so it costs the same on a company with ten invoices and one with
    # ten thousand — the property every other figure on this report already has.
    overdue: list[tuple[int, int, SnakeUtc, float]]


def billing_report(
    session: SnakeSession, cutoff: SnakeUtc, *, minimum_cents: int = 1
) -> BillingReport:
    """The whole billing report: FOUR statements, none of which grows with the data.

    `minimum_cents` defaults to one and not to zero on purpose: at zero the `HAVING` would keep a
    plan whose invoices add up to nothing, which is the row `plans` already shows and shows better.

    `cutoff` is taken rather than read off the clock, and it travels as far as the selector for the
    same reason: a report that asked the time would answer differently on two runs and could not be
    tested. The caller — a view — is the one that knows what 'now' means for the request.
    """
    unpaid_count, unpaid_cents = selectors.unpaid_total(session)
    return BillingReport(
        plans=selectors.plan_stats(session),
        revenue=selectors.revenue_by_plan(session, minimum_cents=minimum_cents),
        unpaid_count=unpaid_count,
        unpaid_cents=unpaid_cents,
        overdue=selectors.overdue_ageing(session, cutoff),
    )
