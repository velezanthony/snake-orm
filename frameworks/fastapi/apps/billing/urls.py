"""Router of the billing domain (plans, subscriptions, invoices and payments): a thin JSON API.

Every endpoint parses the request (Pydantic), calls the use case with flat parameters and translates
the result into JSON (data -> DTO, `Failure` -> HTTPException). Zero queries, zero `commit` here.

THE FIVE READS THE SSR DEMOS' PAGES DRAW answer here as well — the pager, the detail, an invoice's
payments, a customer's invoices and the money report. They were reachable from Django's and Flask's
pages and from no JSON surface at all, which is a client that cannot ask a question the other
surface answers; `shared/tests/test_the_page_and_the_api_reach_one_usecase.py` is what measures it
and `test_the_demos_serve_the_same_routes.py` is what makes these three routers carry the same
paths. Every one of them awaits the `shared.aio` twin of the use case the pages call.

ROUTE ORDER IS LOAD-BEARING IN THIS FILE, unlike in the other two routers. FastAPI matches in
DECLARATION order, so `/invoices/unpaid` and `/invoices/page` have to be declared above
`/invoices/{invoice_id}` or the literal is swallowed by the parameter and answers 422 for a word
that is not a number. Flask sorts its rules by weight and Django's `int` converter refuses a word,
so neither of them depends on the order; here it is the only thing holding the two apart.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from snakeorm import SnakeUtc

from apps.billing import usecases
from apps.billing.usecases import Failure
from apps.deps import SessionDep, http_error
from shared.dto.billing_dto import (
    billing_report_dict,
    invoice_dict,
    invoice_page_dict,
    invoice_with_parties_dict,
    payment_dict,
    plan_dict,
    subscription_dict,
)
from shared.viewmodels.billing_viewmodels import parse_paid

router = APIRouter(prefix="/api/billing", tags=["billing"])


class SubscribeIn(BaseModel):
    """Body for subscribing a user to a plan."""

    user_id: int
    plan_id: int


class InvoiceIn(BaseModel):
    """Body for issuing an invoice against a subscription."""

    amount_cents: int


class PayIn(BaseModel):
    """Body for paying an invoice."""

    method: str


@router.get("/plans")
async def list_plans(session: SessionDep) -> list[dict[str, object]]:
    """Every billing plan."""
    return [plan_dict(p) for p in await usecases.list_plans(session)]


@router.get("/users/{user_id}/subscriptions")
async def subscriptions_of_user(
    user_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """The subscriptions of a user."""
    return [
        subscription_dict(s)
        for s in await usecases.subscriptions_of_user(session, user_id)
    ]


@router.get("/subscriptions/{subscription_id}/invoices")
async def invoices_of_subscription(
    subscription_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """The invoices of a subscription."""
    return [
        invoice_dict(i)
        for i in await usecases.invoices_of_subscription(session, subscription_id)
    ]


@router.get("/users/{user_id}/invoices")
async def invoices_of_customer(
    user_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """Every invoice of a customer, across all their subscriptions, in ONE statement.

    `Invoice.subscription.user_id` is a two-hop navigation the emitter plans as a JOIN. Asking per
    subscription is the N+1 this replaces — invisible on the two-subscription customer the seed
    makes, and a round trip per row on anybody real.

    The rows come back BARE, so they go out bare: this read pays for no joins, and serialising the
    parties off it would raise while the response is being written.
    """
    return [
        invoice_dict(i) for i in await usecases.invoices_of_customer(session, user_id)
    ]


@router.get("/report")
async def billing_report(
    session: SessionDep, minimum_cents: int = 1
) -> dict[str, object]:
    """The money report: FOUR statements, and not one of them grows with the number of rows.

    THE CLOCK IS READ HERE and passed down, exactly as the SSR demos' report view does it. A use
    case that called `now()` itself would answer differently on two runs and could not be tested;
    the handler is the layer that knows what 'now' means for this request.

    It cannot fail: every figure is an aggregate, so a company with no invoices gets zeroes rather
    than a 404.
    """
    return billing_report_dict(
        await usecases.billing_report(
            session, SnakeUtc.now(), minimum_cents=minimum_cents
        )
    )


@router.get("/invoices/unpaid")
async def unpaid_invoices(session: SessionDep) -> list[dict[str, object]]:
    """Every unpaid invoice in the system."""
    return [invoice_dict(i) for i in await usecases.unpaid_invoices(session)]


@router.get("/invoices/page")
async def paginate_invoices(
    session: SessionDep,
    paid: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict[str, object]:
    """One page of invoices with what the pager needs, optionally narrowed to settled or open.

    TWO statements, whatever the page and whatever the filter: the count and the rows. One fewer
    than the stock pager pays, and the difference is the filter — a BOOLEAN, so its options are a
    Python constant instead of a table that has to be read.

    `paid` arrives as TEXT and goes through `parse_paid`, and it is not typed `bool | None` even
    though Pydantic would happily parse `true`/`false` for free. That would give this demo a second
    vocabulary for one filter: the SSR pages post `paid=open` and `paid=paid`, `parse_paid` is the
    single place that decision lives, and a client that reads a listing and posts the filter back is
    the one that discovers the two spellings.
    """
    return invoice_page_dict(
        await usecases.paginate_invoices(
            session, paid=parse_paid(paid), page=page, per_page=per_page
        )
    )


@router.get("/invoices/{invoice_id}")
async def show_invoice(invoice_id: int, session: SessionDep) -> dict[str, object]:
    """One invoice with the chain behind it — subscription, plan and customer; 404 if it is gone.

    ONE statement for four rows: the three hops are to-one, so they are LEFT JOINs on the same
    SELECT. That is what the with-parties shape costs here and why a customer's invoices go out
    bare instead: that read pays for no joins, and a reader who opens ONE invoice wants the names
    rather than three more requests to look them up.
    """
    result = await usecases.show_invoice(session, invoice_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return invoice_with_parties_dict(result)


@router.get("/invoices/{invoice_id}/payments")
async def invoice_payments(
    invoice_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """The payments against an invoice, oldest first; 404 when the invoice does not exist.

    THE 404 COMES FROM `show_invoice` AND NOT FROM `payments_of`, which is deliberate on both sides.
    The use case does not check the invoice exists — its caller on the detail PAGE has already
    fetched it and already had its `not_found`, so a check inside would be a third statement on
    every visit to learn what the caller knows. This endpoint has no such fetch behind it, so it
    makes the one the page already made: same two statements, same answer, and an unknown id gets a
    404 instead of an empty list that reads like "this invoice was never paid".
    """
    found = await usecases.show_invoice(session, invoice_id)
    if isinstance(found, Failure):
        raise http_error(found)
    return [
        payment_dict(payment)
        for payment in await usecases.payments_of(session, invoice_id)
    ]


@router.post("/subscriptions", status_code=201)
async def subscribe(payload: SubscribeIn, session: SessionDep) -> dict[str, object]:
    """Subscribe a user to a plan."""
    return subscription_dict(
        await usecases.subscribe(session, payload.user_id, payload.plan_id)
    )


@router.post("/subscriptions/{subscription_id}/invoices", status_code=201)
async def issue_invoice(
    subscription_id: int, payload: InvoiceIn, session: SessionDep
) -> dict[str, object]:
    """Issue an invoice against a subscription."""
    return invoice_dict(
        await usecases.issue_invoice(session, subscription_id, payload.amount_cents)
    )


@router.post("/invoices/{invoice_id}/pay")
async def pay_invoice(
    invoice_id: int, payload: PayIn, session: SessionDep
) -> dict[str, object]:
    """Pay an invoice. 404 if the invoice does not exist."""
    result = await usecases.pay_invoice(session, invoice_id, payload.method)
    if isinstance(result, Failure):
        raise http_error(result)
    return payment_dict(result)


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def cancel_subscription(subscription_id: int, session: SessionDep) -> None:
    """Cancel a subscription. 404 if the subscription does not exist."""
    result = await usecases.cancel_subscription(session, subscription_id)
    if isinstance(result, Failure):
        raise http_error(result)
