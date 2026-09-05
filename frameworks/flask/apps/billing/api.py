"""JSON API of the billing domain (plans, subscriptions, invoices, payments): thin endpoints.

Every endpoint parses the request, calls the use case with flat parameters and translates the result
into JSON (data -> DTO, `Failure` -> `abort(status)`). `subscribe` and `issue_invoice` never return
a `Failure`. The ORM session is opened by the blog's `before_app_request` hook in `g.session`.

THE FIVE READS AT THE BOTTOM MIRROR THE PAGES, and they exist because they did not. `urls.py` next
door draws the listing, the detail and the report, and those three screens were until now the only
way to reach `paginate_invoices`, `show_invoice`, `payments_of`, `invoices_of_customer` and
`billing_report`. A read reachable from one surface only is a question this one cannot answer, which
is what `shared/tests/test_the_page_and_the_api_reach_one_usecase.py` measures. They call the SAME
use cases the pages call; nothing here re-implements a query.

Billing is still read-only as a section, which is a separate decision and untouched: an invoice is
raised by `orders.settle` and settled by `pay_invoice`, never typed into a form.
"""

from __future__ import annotations

from flask import abort, g, jsonify, request
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from snakeorm import SnakeUtc

from apps import wire
from apps.billing import usecases
from shared.dto.billing_dto import (
    billing_report_dict,
    invoice_dict,
    invoice_page_dict,
    invoice_with_parties_dict,
    payment_dict,
    plan_dict,
    subscription_dict,
)
from shared.usecases.result import FAILURE_STATUS
from shared.viewmodels.billing_viewmodels import parse_paid

billing = Blueprint(
    # `-api` because the plain `billing` belongs to the PAGES in `urls.py`, the way
    # `blog`/`blog-api` and `inventory`/`inventory-api` already split. This blueprint held the
    # plain name while the domain had no pages, which worked exactly until it had some: two
    # blueprints cannot share one `url_for` name.
    "billing-api",
    __name__,
    url_prefix="/api/billing",
    description="Billing: plans, subscriptions, invoices and payments",
)


def _int_arg(name: str, default: int) -> int:
    """A query-string integer, falling back rather than raising: the value comes from a URL.

    The same helper `orders/api.py` carries. `?page=abc` is a mistake somebody typed, not a 500 on a
    listing that has nothing wrong with it; the use case clamps the number afterwards.
    """
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


@billing.get("/plans")
def list_plans() -> ResponseReturnValue:
    """Every available plan."""
    return jsonify([plan_dict(p) for p in usecases.list_plans(g.session)])


@billing.get("/users/<int:user_id>/subscriptions")
def subscriptions_of_user(user_id: int) -> ResponseReturnValue:
    """The subscriptions of a user."""
    return jsonify(
        [
            subscription_dict(s)
            for s in usecases.subscriptions_of_user(g.session, user_id)
        ]
    )


@billing.get("/subscriptions/<int:subscription_id>/invoices")
def invoices_of_subscription(subscription_id: int) -> ResponseReturnValue:
    """The invoices of a subscription."""
    return jsonify(
        [
            invoice_dict(i)
            for i in usecases.invoices_of_subscription(g.session, subscription_id)
        ]
    )


@billing.get("/users/<int:user_id>/invoices")
def invoices_of_customer(user_id: int) -> ResponseReturnValue:
    """Every invoice of a customer, across all their subscriptions, in ONE statement.

    `Invoice.subscription.user_id` is a two-hop navigation the emitter plans as a JOIN. Asking per
    subscription is the N+1 this replaces — invisible on the two-subscription customer the seed
    makes, and a round trip per row on anybody real.

    The rows come back BARE, so they go out bare: this read pays for no joins, and serialising the
    parties off it would raise while the response is being written.
    """
    return jsonify(
        [invoice_dict(i) for i in usecases.invoices_of_customer(g.session, user_id)]
    )


@billing.get("/invoices/unpaid")
def unpaid_invoices() -> ResponseReturnValue:
    """Every invoice still awaiting payment."""
    return jsonify([invoice_dict(i) for i in usecases.unpaid_invoices(g.session)])


@billing.get("/invoices/page")
def paginate_invoices() -> ResponseReturnValue:
    """One page of invoices with what the pager needs, optionally narrowed to settled or open.

    TWO statements, whatever the page and whatever the filter: the count and the rows. One fewer
    than the stock pager pays, and the difference is the filter — a BOOLEAN, so its options are a
    Python constant instead of a table that has to be read.

    `?paid=` goes through `parse_paid`, the SAME function the listing page uses. A demo whose page
    posts `paid=open` and whose API wants `paid=false` has two vocabularies for one filter, and the
    client that reads a listing and posts the filter back is the one that finds out.
    """
    return jsonify(
        invoice_page_dict(
            usecases.paginate_invoices(
                g.session,
                paid=parse_paid(request.args.get("paid")),
                page=_int_arg("page", 1),
                per_page=_int_arg("per_page", 20),
            )
        )
    )


@billing.get("/report")
def billing_report() -> ResponseReturnValue:
    """The money report: FOUR statements, and not one of them grows with the number of rows.

    THE CLOCK IS READ HERE and passed down, exactly as the report PAGE does it. A use case that
    called `now()` itself would answer differently on two runs and could not be tested; the handler
    is the layer that knows what 'now' means for this request.

    It cannot fail: every figure is an aggregate, so a company with no invoices gets zeroes rather
    than a 404.
    """
    return jsonify(
        billing_report_dict(
            usecases.billing_report(
                g.session,
                SnakeUtc.now(),
                minimum_cents=_int_arg("minimum_cents", 1),
            )
        )
    )


@billing.get("/invoices/<int:invoice_id>")
def show_invoice(invoice_id: int) -> ResponseReturnValue:
    """One invoice with the chain behind it — subscription, plan and customer; 404 if it is gone.

    ONE statement for four rows: the three hops are to-one, so they are LEFT JOINs on the same
    SELECT. That is what the with-parties shape costs here and why a customer's invoices go out
    bare instead: that read pays for no joins, and a reader who opens ONE invoice wants the names
    rather than three more requests to look them up.
    """
    result = usecases.show_invoice(g.session, invoice_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(invoice_with_parties_dict(result))


@billing.get("/invoices/<int:invoice_id>/payments")
def invoice_payments(invoice_id: int) -> ResponseReturnValue:
    """The payments against an invoice, oldest first; 404 when the invoice does not exist.

    THE 404 COMES FROM `show_invoice` AND NOT FROM `payments_of`, which is deliberate on both sides.
    The use case does not check the invoice exists — its caller on the detail PAGE has already
    fetched it and already had its `not_found`, so a check inside would be a third statement on
    every visit to learn what the caller knows. This endpoint has no such fetch behind it, so it
    makes the one the page already made: same two statements, same answer, and an unknown id gets a
    404 instead of an empty list that reads like "this invoice was never paid".
    """
    found = usecases.show_invoice(g.session, invoice_id)
    if isinstance(found, usecases.Failure):
        abort(FAILURE_STATUS[found.reason])
    payments = usecases.payments_of(g.session, invoice_id)
    return jsonify([payment_dict(payment) for payment in payments])


@billing.post("/subscriptions")
def subscribe() -> ResponseReturnValue:
    """Subscribe a user to a plan."""
    payload = wire.json_object(request)
    subscription = usecases.subscribe(
        g.session,
        wire.integer(payload.get("user_id")),
        wire.integer(payload.get("plan_id")),
    )
    return jsonify(subscription_dict(subscription)), 201


@billing.post("/subscriptions/<int:subscription_id>/invoices")
def issue_invoice(subscription_id: int) -> ResponseReturnValue:
    """Issue an invoice against a subscription."""
    payload = wire.json_object(request)
    invoice = usecases.issue_invoice(
        g.session, subscription_id, wire.integer(payload.get("amount_cents"))
    )
    return jsonify(invoice_dict(invoice)), 201


@billing.post("/invoices/<int:invoice_id>/pay")
def pay_invoice(invoice_id: int) -> ResponseReturnValue:
    """Charge an invoice (create the payment and mark it paid). 404 if the invoice does not exist."""
    payload = wire.json_object(request)
    result = usecases.pay_invoice(
        g.session, invoice_id, wire.text(payload.get("method"))
    )
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(payment_dict(result))


@billing.delete("/subscriptions/<int:subscription_id>")
def cancel_subscription(subscription_id: int) -> ResponseReturnValue:
    """Cancel a subscription. 404 if it does not exist."""
    result = usecases.cancel_subscription(g.session, subscription_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return "", 204
