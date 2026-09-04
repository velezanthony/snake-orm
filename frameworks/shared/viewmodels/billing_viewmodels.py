"""billing view models: the three pages of the money domain — list, detail and report.

THREE and not five, and the plan chose the three rather than trimming the five. `inventory` and
`orders` get the whole CRUD taxonomy because a stock level is corrected and an order is edited; an
invoice is neither. It is RAISED by an operation and SETTLED by another, and a form that let somebody
retype an amount would be a demo of the one thing accounting software must never offer. So billing
shows the READ side of money, which is where the interesting queries were anyway.

The four rules of `inventory_viewmodels` hold here unchanged — go through the use cases, return a
`TypedDict`, hand back a `Failure` untouched, emit nothing but primitives — and this module adds one
observation of its own, which is about the type of money.

MONEY IS STORED TWO WAYS IN THIS REPOSITORY AND THAT IS ON PURPOSE. `billing` counts integer CENTS
and `orders` stores a `NUMERIC(12,2)`, and both are defensible: cents are exact on every engine
including the ones with no decimal type, and a `NUMERIC` is what a database ought to be asked for
when it has one. What is not defensible is converting between them casually, so the conversion lives
in ONE function here and `orders_viewmodels` delegates to it rather than keeping a second copy.
`cents / 100` would go through binary floating point, which is the precise thing an exact type exists
to avoid; `Decimal(cents) / 100` does not.

That single conversion is also why this module is the one that owns it: the domain that stores cents
is the domain that knows what they mean.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

from datetime import datetime

from snakeorm import SnakeSession, SnakeUtc

from shared.models import Invoice, Payment, Plan, PlanStats
from shared.usecases import billing_usecases as usecases
from shared.usecases.result import Failure

# The three values the settlement filter can take, as a form posts them back. `""` is "everything"
# and not `None`, because a query string has no `None` in it: what arrives from a browser is an
# absent key or an empty one, and turning both into the same thing HERE is what stops two demos
# inventing two spellings of "no filter".
PAID_ANY = ""
PAID_ONLY = "paid"
OPEN_ONLY = "open"

_PAID_LABELS: dict[str, str] = {
    PAID_ANY: "All invoices",
    PAID_ONLY: "Settled",
    OPEN_ONLY: "Outstanding",
}


def money_from_cents(cents: int) -> str:
    """Integer cents as money with two decimals. Through `Decimal`, never through a float.

    The ONE place in the repository that turns this domain's storage into something a person reads.
    `orders_viewmodels` calls it rather than keeping a copy, because two formatters are two rounding
    rules waiting to disagree on the one kind of value where disagreeing is a bug somebody notices on
    a bank statement.
    """
    return f"{Decimal(cents) / 100:.2f}"


def paid_label(value: str) -> str:
    """What a person reads for a settlement filter. `KeyError` for an unknown one, on purpose.

    A fourth filter value added without a label has to fail loudly instead of printing an empty
    option, which is the bargain `nav.section` and `orders_viewmodels.state_label` both make.
    """
    return _PAID_LABELS[value]


def parse_paid(value: str | None) -> bool | None:
    """Turns a query-string value into the filter: `None` for "everything", else the boolean.

    Anything unrecognised means NO filter rather than an error, which is the same call
    `orders_viewmodels.parse_state` makes and for the same reason: a typo in a hand-edited URL is not
    a 500. It differs from the pilot's treatment of an unknown warehouse id, and the difference is
    real — an unknown id is still a filter the engine can run and correctly matches nothing, while
    `paid=maybe` cannot be turned into a filter at all.
    """
    if value == PAID_ONLY:
        return True
    if value == OPEN_ONLY:
        return False
    return None


class PaidOption(TypedDict):
    """One settlement filter as a `<select>` option: the value it posts back and the words it shows."""

    value: str
    label: str


class InvoiceRow(TypedDict):
    """One invoice with the WHOLE chain behind it already flattened: subscription, plan, customer.

    Those three come from a three-hop to-one navigation (`invoice -> subscription -> plan` and
    `-> user`), all of them LEFT JOINs on the same SELECT. Flattening them here is the deepest case
    in this repository of the rule this layer exists for: a template writing
    `invoice.subscription.plan.name` would be firing TWO relation loads per row, inside the renderer,
    where nothing counts queries.

    `status_label` is here rather than an `{% if %}` in two templates. `paid` travels as well,
    because a template still wants to colour the row, and a boolean is a better thing to branch on
    than a string somebody might translate.
    """

    id: int
    amount: str
    paid: bool
    status_label: str
    issued_at: str
    subscription_id: int
    customer_id: int
    customer: str
    plan: str
    plan_price: str


class PaymentRow(TypedDict):
    """One payment against an invoice: how much, how, and when. The to-many of the detail page."""

    id: int
    amount: str
    method: str
    paid_at: str


class InvoiceListPage(TypedDict):
    """The listing plus its pager and its filter: everything the page needs to redraw itself.

    `paid` comes back as the STRING the form posted rather than as the boolean it was parsed into,
    so the template can mark the selected option without turning three values back into three cases.
    `prev_page`/`next_page` arrive clamped, so the template never does arithmetic on a page number.
    """

    rows: list[InvoiceRow]
    filters: list[PaidOption]
    paid: str
    page: int
    pages: int
    total: int
    has_prev: bool
    has_next: bool
    prev_page: int
    next_page: int


class InvoiceDetailPage(TypedDict):
    """One invoice in full: the row, its payments, and whether the two add up.

    `paid_total` and `outstanding` are the reason this page is worth having. An invoice carries a
    `paid` flag AND a list of partial payments, and nothing in the schema forces the two to agree —
    so an invoice marked settled whose payments fall short is a state the database happily holds and
    only a page like this one shows. `is_short` says it out loud rather than leaving a reader to
    subtract two formatted strings.
    """

    invoice: InvoiceRow
    payments: list[PaymentRow]
    payment_count: int
    paid_total: str
    outstanding: str
    is_short: bool


class PlanStatsRow(TypedDict):
    """One plan with how many subscriptions it has: the `annotate` row, flattened.

    A plan nobody subscribes to comes back with a zero, which is the row a `GROUP BY` over the
    subscriptions would silently drop and the one a "which tariffs are dead" question is about.
    """

    id: int
    name: str
    price: str
    subscription_count: int


class PlanRevenueRow(TypedDict):
    """One plan that has actually invoiced money: the `GROUP BY` + `HAVING` row.

    There is no id on it, and that is what a group by a VALUE looks like: the rows were folded on the
    plan's name, so there is no single plan row left to take an id from. The shape says so instead of
    inventing one.
    """

    plan: str
    invoice_count: int
    revenue: str


class OverdueRow(TypedDict):
    """One debt past its due date, as strings a template prints without deciding anything.

    `due` and `collected` are computed by the ENGINE and only FORMATTED here, which is the whole
    point of the section: the due date is `issued_at + 30 days` and the collected share is a real
    division of two integer-cent columns. Doing either in Python would mean pulling every open
    invoice and its payments across the wire to answer a question the database already answered.
    """

    invoice_id: int
    amount: str
    due: str
    collected: str


class BillingReportPage(TypedDict):
    """The money report: the roll call, the revenue, what is still open, and the gap between them.

    `silent_plans` is the figure the page exists for and it is computed HERE, from the two lists, for
    the reason every derived value in this layer is: it is one set subtraction, and two templates
    write one set subtraction two ways. A plan with subscribers and no revenue is either a tariff
    nobody is being billed for or a billing job that stopped running, and both are worth seeing on
    the first screen rather than inferred by a reader comparing two tables.
    """

    plans: list[PlanStatsRow]
    revenue: list[PlanRevenueRow]
    minimum: str
    overdue: list[OverdueRow]
    unpaid_count: int
    unpaid_total: str
    silent_plans: list[str]


def _paid_options() -> list[PaidOption]:
    """The three filter options, in the order they are offered. NO query: they are a constant.

    Which is why this listing costs one statement less than the pilot's: `inventory` filters by a
    TABLE of warehouses and has to read it, and this one filters by a boolean the code already knows.
    """
    return [{"value": value, "label": label} for value, label in _PAID_LABELS.items()]


def _invoice_row(invoice: Invoice) -> InvoiceRow:
    """An invoice flattened, doing the three to-one hops the template must not do.

    It REQUIRES the invoice to arrive with `subscription`, its `plan` and its `user` loaded, which
    every use case that feeds it does with a single `include`. Reading them off a bare row would work
    and would cost two queries per line — the exact N+1 this layer was put in front of, moved one
    file over.
    """
    subscription = invoice.subscription
    return {
        "id": invoice.id,
        "amount": money_from_cents(invoice.amount_cents),
        "paid": invoice.paid,
        "status_label": paid_label(PAID_ONLY if invoice.paid else OPEN_ONLY),
        "issued_at": invoice.issued_at.isoformat(),
        "subscription_id": invoice.subscription_id,
        "customer_id": subscription.user_id,
        "customer": subscription.user.username,
        "plan": subscription.plan.name,
        "plan_price": money_from_cents(subscription.plan.price_cents),
    }


def _payment_row(payment: Payment) -> PaymentRow:
    """A payment flattened: money as text, the timestamp as ISO, nothing left to format."""
    return {
        "id": payment.id,
        "amount": money_from_cents(payment.amount_cents),
        "method": payment.method,
        "paid_at": payment.paid_at.isoformat(),
    }


def _plan_stats_row(stats: PlanStats) -> PlanStatsRow:
    """A `@snake_result` flattened: the plan's own columns and the aggregate beside them."""
    plan: Plan = stats.plan
    return {
        "id": plan.id,
        "name": plan.name,
        "price": money_from_cents(plan.price_cents),
        "subscription_count": stats.subscription_count,
    }


def invoice_list(
    session: SnakeSession,
    *,
    paid: str = PAID_ANY,
    page: int = 1,
    per_page: int = 20,
) -> InvoiceListPage:
    """The invoice listing: a page of rows, its pager, and the settlement filter. TWO statements.

    Two, always: the count and the page of rows. Neither depends on how many rows come back, which is
    what makes the page's cost flat — and the third statement the pilot pays is the table of
    warehouses its filter is made of. This filter is a boolean, so its options are a Python constant.

    It never returns a `Failure`. An unrecognised filter value is no filter at all, and an empty page
    is an answer.
    """
    result = usecases.paginate_invoices(
        session, paid=parse_paid(paid), page=page, per_page=per_page
    )
    return {
        "rows": [_invoice_row(invoice) for invoice in result.rows],
        "filters": _paid_options(),
        "paid": paid if paid in _PAID_LABELS else PAID_ANY,
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


def invoice_detail(
    session: SnakeSession, invoice_id: int
) -> InvoiceDetailPage | Failure:
    """One invoice: its row, the chain behind it, and every payment against it. TWO statements.

    The arithmetic is done here and not in the template, and it is the arithmetic that makes the page
    worth loading: the sum of the payments against the amount owed. Nothing in the schema forces
    those two to agree, so an invoice flagged settled with half of it paid is a row the database will
    hold forever and only this page will show.
    """
    invoice = usecases.show_invoice(session, invoice_id)
    if isinstance(invoice, Failure):
        return invoice
    payments = usecases.payments_of(session, invoice_id)
    collected = sum(payment.amount_cents for payment in payments)
    outstanding = invoice.amount_cents - collected
    return {
        "invoice": _invoice_row(invoice),
        "payments": [_payment_row(payment) for payment in payments],
        "payment_count": len(payments),
        "paid_total": money_from_cents(collected),
        # Never negative on the page: an overpayment is a real thing and "what is still owed" is
        # zero, not a debt the customer has to the company. The refund is somebody else's page.
        "outstanding": money_from_cents(max(0, outstanding)),
        "is_short": invoice.paid and outstanding > 0,
    }


def _day_of(value: object) -> str:
    """The calendar day of a value that may arrive as a datetime or as ISO-8601 text.

    Not defensive coding for its own sake: the two shapes are two ENGINES. A computed date comes back
    typed from PostgreSQL and as text from SQLite, which has no date type to type it with, and the
    demos run on both from the same `.env`. Formatting in one place is what keeps a template from
    growing an `if` about which database it is talking to.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10]


def _overdue_row(
    invoice_id: int, amount_cents: int, due: SnakeUtc, collected: float
) -> OverdueRow:
    """One ageing row, formatted. The FRACTION is what arrives and a percentage is what is shown.

    Both matter and they are not the same thing. What the engine computed is a real fraction — with
    integer division it would have been `0` for every partly-paid invoice — and what a person reads
    on a debt is a percentage. Formatting the honest number is a display decision; computing a
    dishonest one would not be.

    The date is rendered as a plain day because the term is counted in days: an hour on a due date is
    noise, and printing it would invite somebody to compare it against a timestamp.

    AND THE DUE DATE ARRIVES ENGINE-SHAPED, which is worth knowing before it surprises somebody. The
    row mapper converts a stored COLUMN because it knows what that column was declared as; a computed
    expression has no column to know, so what comes back is whatever the driver hands over. On SQLite
    that is ISO-8601 text, because SQLite has no date type at all — the same fact `Cap.TIMESTAMPTZ`
    already declares for stored timestamps. `_day_of` takes both shapes rather than pretending only
    one exists.
    """
    return {
        "invoice_id": invoice_id,
        "amount": money_from_cents(amount_cents),
        "due": _day_of(due),
        "collected": f"{collected * 100:.1f}%",
    }


def billing_report(
    session: SnakeSession, cutoff: SnakeUtc, *, minimum_cents: int = 1
) -> BillingReportPage:
    """The money report: THREE statements, and none of them grows with the data.

    It never returns a `Failure`: every figure is an aggregate, and a company with no invoices is an
    answer rather than a missing page.
    """
    report = usecases.billing_report(session, cutoff, minimum_cents=minimum_cents)
    earning = {row[0] for row in report.revenue}
    return {
        "plans": [_plan_stats_row(stats) for stats in report.plans],
        "revenue": [
            {
                "plan": name,
                "invoice_count": issued,
                "revenue": money_from_cents(cents),
            }
            for name, issued, cents in report.revenue
        ],
        "minimum": money_from_cents(minimum_cents),
        "overdue": [_overdue_row(*row) for row in report.overdue],
        "unpaid_count": report.unpaid_count,
        "unpaid_total": money_from_cents(report.unpaid_cents),
        # Subscribed to and never invoiced: the gap between the two queries above, named. Only plans
        # with subscribers count — a tariff nobody is on is not silent, it is unused.
        "silent_plans": [
            stats.plan.name
            for stats in report.plans
            if stats.subscription_count > 0 and stats.plan.name not in earning
        ],
    }
