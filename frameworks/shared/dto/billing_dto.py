"""DTOs for the billing domain (plans, subscriptions, invoices, payments). Flat and JSON-able.

MONEY LEAVES THIS DOMAIN AS INTEGER CENTS, which is the one thing to know before reading a key. The
other domains store a `NUMERIC(12,2)` and their DTOs emit it as a STRING, because `json.dumps` on a
float is precisely where the cent goes missing. Billing has no such problem to solve: it counts
integer cents, and an integer is exact in JSON. Turning them into `"42.00"` here would be FORMATTING
— a display decision that belongs to whoever is drawing the figure, and `billing_viewmodels` is
where the pages make it. A client that gets a string cannot add two of them up.

An instant goes out in its textual ISO form, identical on the three engines.

THE RELATIONSHIPS ARE OPTIONAL AND THE SHAPE SAYS SO, the same split `orders_dto` sets out at
length. An invoice points at a subscription, which points at a plan and a customer, and only the
reads that asked for that chain have it: `invoices_of_customer` reads invoices BARE on purpose,
while `show_invoice` and `paginate_invoices` pay for three LEFT JOINs because a page shows the
names. So `invoice_dict` serialises the id, which is always there, and `invoice_with_parties_dict`
is what a caller that included them calls. Reaching for `invoice.subscription.plan.name` in the
plain one raises `SnakeRelationshipNotLoaded` — the ORM shouting rather than firing two queries per
row inside a response, which is the worst place to find out.
"""

from __future__ import annotations

from datetime import datetime

from snakeorm import SnakeUtc

from shared.dto import iso
from shared.models import Invoice, Payment, Plan, PlanStats, Subscription
from shared.usecases.billing_usecases import BillingReport, InvoicePage


def plan_dict(plan: Plan) -> dict[str, object]:
    """A plan as a dict: id, name and price in cents."""
    return {"id": plan.id, "name": plan.name, "price_cents": plan.price_cents}


def subscription_dict(subscription: Subscription) -> dict[str, object]:
    """A subscription as a dict."""
    return {
        "id": subscription.id,
        "active": subscription.active,
        "user_id": subscription.user_id,
        "plan_id": subscription.plan_id,
        "started_at": iso(subscription.started_at),
    }


def invoice_dict(invoice: Invoice) -> dict[str, object]:
    """An invoice as a dict, with its subscription as an id. Needs NO relationship loaded.

    This is the shape for a read that did not pay for the chain — `invoices_of_customer` is the one
    in this domain — and it is a different function from its sibling below rather than a flag on
    one, because the difference is not cosmetic: the sibling raises on a row read this way.
    """
    return {
        "id": invoice.id,
        "amount_cents": invoice.amount_cents,
        "paid": invoice.paid,
        "subscription_id": invoice.subscription_id,
        "issued_at": iso(invoice.issued_at),
    }


def invoice_with_parties_dict(invoice: Invoice) -> dict[str, object]:
    """An invoice plus the plan it bills and the customer who owes it. Needs `with_parties` loaded.

    THREE hops deep and all to-one — `invoice -> subscription -> plan` and `-> user` — which the
    reads that feed this arrange as LEFT JOINs on one statement. That is why this shape costs
    nothing extra HERE and would cost two queries per row if it were used on a bare invoice.

    It EXTENDS the bare shape rather than replacing it, so a client that reads a customer's invoices
    and then opens one gets the same names for the same facts and only more of them.
    """
    subscription = invoice.subscription
    return {
        **invoice_dict(invoice),
        "customer_id": subscription.user_id,
        "customer": subscription.user.username,
        "plan_id": subscription.plan_id,
        "plan": subscription.plan.name,
        "plan_price_cents": subscription.plan.price_cents,
    }


def invoice_page_dict(page: InvoicePage) -> dict[str, object]:
    """A page of invoices WITH what the pager needs, travelling with the rows rather than beside them.

    The four go out together because they are ONE answer, which is the argument `InvoicePage` is
    built on: a client that asks for the total separately is the client that filters the two
    questions differently, and then draws a pager saying 47 over a listing showing a different 47.

    The rows take the with-parties shape because `paginate_invoices` includes the chain. Serialising
    them bare would throw away three columns the statement already fetched.
    """
    return {
        "rows": [invoice_with_parties_dict(invoice) for invoice in page.rows],
        "total": page.total,
        "page": page.page,
        "pages": page.pages,
    }


def payment_dict(payment: Payment) -> dict[str, object]:
    """A payment as a dict."""
    return {
        "id": payment.id,
        "amount_cents": payment.amount_cents,
        "method": payment.method,
        "invoice_id": payment.invoice_id,
        "paid_at": iso(payment.paid_at),
    }


def plan_stats_dict(stats: PlanStats) -> dict[str, object]:
    """A plan with how many subscriptions it has, from ONE annotated read.

    The row is a `SnakeResult[Plan]`, so the plan arrives as a WHOLE model under `.plan` rather than
    as flattened columns — which is the shape `annotate` gives and the reason this serialiser reaches
    one level in, exactly as `customer_orders_dict` does for its own annotate.
    """
    return {**plan_dict(stats.plan), "subscription_count": stats.subscription_count}


def plan_revenue_dict(row: tuple[str, int, int]) -> dict[str, object]:
    """One `GROUP BY ... HAVING` row: a plan that has actually invoiced money.

    There is no id on it and that is what a group by a VALUE looks like — the rows were folded on
    the plan's name, so there is no single plan row left to take an id from. The shape says so
    instead of inventing one.
    """
    plan, invoice_count, revenue_cents = row
    return {
        "plan": plan,
        "invoice_count": invoice_count,
        "revenue_cents": revenue_cents,
    }


def _due_day(value: object) -> str:
    """The calendar day of a due date that may arrive as an instant or as ISO-8601 text.

    Not defensive coding: the two shapes are two ENGINES. The row mapper converts a stored COLUMN
    because it knows what that column was declared as, and this date is COMPUTED — `issued_at + 30
    days` — so there is no declaration to go on and what comes back is whatever the driver handed
    over. Postgres types it; SQLite has no date type at all, the fact `Cap.TIMESTAMPTZ` already
    declares, so it arrives as text. The demos run on both from one `.env`, so a serialiser that
    called `.isoformat()` would raise on one of them inside a response.

    It takes `object` rather than `SnakeUtc` for that reason and not out of looseness: the annotation
    on the selector describes what the column MEANS, and this function is about what the driver
    delivers. `billing_viewmodels._day_of` makes the same call for the page.

    A plain day, because the term is counted in days: an hour on a due date is noise, and printing
    it would invite somebody to compare it against a timestamp.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10]


def overdue_dict(row: tuple[int, int, SnakeUtc | str, float]) -> dict[str, object]:
    """One debt past its due date: what is owed, when it fell due, and the share already collected.

    The fraction goes out RAW — `0.2`, not `"20.0%"` — because that is what the engine computed and
    a percentage is a display decision. With integer division it would have been `0` for every
    partly-paid invoice; formatting the honest number belongs to whoever draws it.
    """
    invoice_id, amount_cents, due, collected = row
    return {
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "due": _due_day(due),
        "collected": collected,
    }


def billing_report_dict(report: BillingReport) -> dict[str, object]:
    """The whole billing report as one payload: FOUR statements, FIVE keys, and the count is the point.

    Four and five and not four and four, because `unpaid_count` and `unpaid_cents` are two halves of
    one sentence read in ONE statement: on a page about money, two numbers measured a moment apart
    is worse than one number missing.

    `order_report_dict` shipped five of `OrderReport`'s six fields and silently dropped `baskets`,
    which is the failure mode a report serialiser has: nothing raises, the payload looks complete,
    and a client never learns the figure exists. It was caught by reading the dataclass, not by
    reading the payload — so `test_billing_dto.py` asks `dataclasses.fields(BillingReport)` rather
    than a list of keys, and a sixth figure added to the report fails until it reaches here. It is
    fixed, and `test_a_report_payload_carries_every_figure.py` now makes the same count over EVERY
    report DTO in this package, so the next one does not need to be remembered.

    `plans` and `revenue` are meant to be read SIDE BY SIDE, which is why both travel: a plan that
    appears in the first with subscribers and is missing from the second has never invoiced
    anything, and that is a billing bug only the two lists together reveal.
    """
    return {
        "plans": [plan_stats_dict(stats) for stats in report.plans],
        "revenue": [plan_revenue_dict(row) for row in report.revenue],
        "unpaid_count": report.unpaid_count,
        "unpaid_cents": report.unpaid_cents,
        "overdue": [overdue_dict(row) for row in report.overdue],
    }
