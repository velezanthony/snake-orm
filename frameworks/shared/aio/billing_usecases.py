"""billing domain (plans, subscriptions, invoices), asked of an `AsyncSession`.

The twin of `shared/usecases/billing_usecases.py`: same names, same parameters, same answers —
including the same `Failure` reasons, because a reason is what the user reads and two wordings of one
refusal is the drift this package's nets exist to catch. What differs is one keyword per statement.

THE PAGES' FIVE READS ARE MIRRORED HERE TOO, and this paragraph used to say the opposite: "not
mirrored, because the FastAPI demo serves no report endpoint". It does now — `paginate_invoices`,
`show_invoice`, `payments_of`, `invoices_of_customer` and `billing_report` each answer at
`/api/billing/`, on all three demos, because a read the SSR pages could reach and the JSON surface
could not is a client that cannot ask a question the other surface answers. A twin whose absence is
justified by an endpoint that has since been written is the reason `test_async_mirror.py` compares
the two modules by NAME instead of trusting a sentence like the one that was here.

The queries are NOT rebuilt here: every fragment (`plans_query`, `subscriptions_of`, `invoices_of`,
`unpaid_invoices_query`, `subscription_by_id`, `invoice_by_id`) comes from the synchronous selectors,
unchanged, because a `SnakeQuery` has no colour. That is why the SQL of this module and of its twin is
identical by construction rather than by agreement.
"""

from __future__ import annotations


from snakeorm import SnakeUtc, AsyncSession

from shared.models import Invoice, Payment, Plan, Subscription
from shared.selectors.billing_selectors import (
    invoice_by_id,
    invoice_listing,
    invoice_with_parties_by_id,
    invoices_of,
    invoices_of_customer as invoices_of_customer_query,
    open_invoices_query,
    overdue_columns,
    overdue_query,
    payments_of_invoice,
    plan_stats_aggregates,
    plan_stats_query,
    plans_query,
    revenue_by_plan_columns,
    revenue_by_plan_query,
    subscription_by_id,
    subscriptions_of,
    unpaid_invoices_query,
    unpaid_total_columns,
    with_parties,
)
from shared.models import PlanStats
from shared.services.billing_services import PAYMENT_KINDS
from shared.usecases.billing_usecases import BillingReport, InvoicePage
from shared.usecases.result import Failure


async def list_plans(session: AsyncSession) -> list[Plan]:
    """Every available plan."""
    return await session.all(plans_query())


async def subscriptions_of_user(
    session: AsyncSession, user_id: int
) -> list[Subscription]:
    """A user's subscriptions, with their plan loaded."""
    return await session.all(subscriptions_of(user_id))


async def invoices_of_subscription(
    session: AsyncSession, subscription_id: int
) -> list[Invoice]:
    """A subscription's invoices."""
    return await session.all(invoices_of(subscription_id))


async def invoices_of_customer(session: AsyncSession, user_id: int) -> list[Invoice]:
    """Every invoice of a customer, across all their subscriptions, in ONE statement.

    It consumes the SAME fragment the synchronous twin does: the two-hop navigation has no colour,
    so a second copy of the `WHERE` is a second thing that can drift.
    """
    return await session.all(invoices_of_customer_query(user_id))


async def unpaid_invoices(session: AsyncSession) -> list[Invoice]:
    """Every invoice still awaiting payment (for the collector)."""
    return await session.all(unpaid_invoices_query())


async def subscribe(session: AsyncSession, user_id: int, plan_id: int) -> Subscription:
    """Signs a user up to a plan and commits the subscription."""
    subscription = await session.add(
        Subscription(user_id=user_id, plan_id=plan_id, started_at=SnakeUtc.now())
    )
    await session.commit()
    return subscription


async def cancel_subscription(
    session: AsyncSession, subscription_id: int
) -> None | Failure:
    """Cancels a subscription; `not_found` if it does not exist."""
    subscription = await session.first(subscription_by_id(subscription_id))
    if subscription is None:
        return Failure("not_found")
    subscription.active = False
    await session.update(subscription)
    await session.commit()
    return None


async def issue_invoice(
    session: AsyncSession, subscription_id: int, amount_cents: int
) -> Invoice:
    """Issues an invoice for a subscription and commits it."""
    invoice = await session.add(
        Invoice(
            amount_cents=amount_cents,
            subscription_id=subscription_id,
            issued_at=SnakeUtc.now(),
        )
    )
    await session.commit()
    return invoice


async def pay_invoice(
    session: AsyncSession, invoice_id: int, method: str, **details: str
) -> Payment | Failure:
    """Collects an invoice (creates the payment and marks it paid); `not_found` if the invoice is gone.

    The KIND comes from the word through the same `PAYMENT_KINDS` mapping the synchronous twin uses,
    and not through a copy of it: a second table of four entries is a second table that can drift,
    and the two would then disagree about what a payment can be.
    """
    kind = PAYMENT_KINDS.get(method)
    if kind is None:
        return Failure("unknown_method")
    invoice = await session.first(invoice_by_id(invoice_id))
    if invoice is None:
        return Failure("not_found")
    payment = await session.add(
        kind(
            amount_cents=invoice.amount_cents,
            invoice_id=invoice_id,
            paid_at=SnakeUtc.now(),
            **details,
        )
    )
    invoice.paid = True
    await session.update(invoice)
    await session.commit()
    return payment


async def paginate_invoices(
    session: AsyncSession,
    *,
    paid: bool | None = None,
    page: int = 1,
    per_page: int = 20,
) -> InvoicePage:
    """A page of invoices, optionally narrowed to the settled or the open ones. TWO statements.

    The two run in the same ORDER as the synchronous twin —count, then rows— and that is not a
    stylistic echo: the parity test compares the SQL both colours emit, statement by statement, so
    awaiting them in a different order is a failure even when every statement is identical.
    """
    per_page = max(1, per_page)
    total = await session.count(invoice_listing(paid=paid))
    pages = max(1, -(-total // per_page))
    page = min(max(1, page), pages)
    rows = await session.all(
        with_parties(invoice_listing(paid=paid))
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    return InvoicePage(rows=rows, total=total, page=page, pages=pages)


async def show_invoice(session: AsyncSession, invoice_id: int) -> Invoice | Failure:
    """One invoice with its subscription, plan and user loaded; `not_found` if it is gone."""
    invoice = await session.first(invoice_with_parties_by_id(invoice_id))
    return invoice if invoice is not None else Failure("not_found")


async def payments_of(session: AsyncSession, invoice_id: int) -> list[Payment]:
    """The payments against an invoice, WITHOUT checking that the invoice exists.

    The caller that needs the difference — the detail page — has already fetched the invoice and
    already got its `not_found`.
    """
    return await session.all(payments_of_invoice(invoice_id))


async def billing_report(
    session: AsyncSession, cutoff: SnakeUtc, *, minimum_cents: int = 1
) -> BillingReport:
    """The whole billing report: FOUR statements, none of which grows with the data.

    The four are awaited in the synchronous twin's order —the open total, then the roll call, then
    the revenue— because the parity test reads the emitted SQL as a sequence. Building the three
    into locals in whatever order reads best and assembling the result afterwards is exactly how the
    inventory report first drifted, and it drifted with every statement individually correct.
    """
    count_col, sum_col = unpaid_total_columns()
    open_rows = await session.select(open_invoices_query(), count_col, sum_col)
    unpaid_count, unpaid_cents = (
        (int(open_rows[0][0]), int(open_rows[0][1] or 0)) if open_rows else (0, 0)
    )
    plans = await session.annotate(
        plan_stats_query(), PlanStats, **plan_stats_aggregates()
    )
    name_col, invoices_col, cents_col = revenue_by_plan_columns()
    revenue_rows = await session.select(
        revenue_by_plan_query(minimum_cents=minimum_cents),
        name_col,
        invoices_col,
        cents_col,
    )
    id_col, amount_col, due_col, collected_col = overdue_columns()
    overdue = await session.select(
        overdue_query(cutoff), id_col, amount_col, due_col, collected_col
    )
    return BillingReport(
        plans=plans,
        revenue=[
            (name, int(issued), int(cents or 0)) for name, issued, cents in revenue_rows
        ],
        unpaid_count=unpaid_count,
        unpaid_cents=unpaid_cents,
        overdue=overdue,
    )
