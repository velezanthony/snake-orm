"""Thin JSON API for the billing domain (plans, subscriptions, invoices, payments): DRF over `shared`.

Thin views (`@api_view`): they parse the request, call the use case with flat parameters and
serialize with the shared DTOs (data) or map the `Failure` to its status (error). Zero queries, zero
`commit`. The SnakeORM session is hung on `request.snake_session` by `SnakeSessionMiddleware` (DRF
wraps the request, but delegates the attribute to the Django request). Since DRF handles CSRF,
`@csrf_exempt` is no longer needed; `@extend_schema` documents each operation at `/api/docs`
(drf-spectacular).

Since Django routes a URL to ONE view, the `subscriptions/{id}/invoices` route (GET list + POST
issue) is handled by a single view that dispatches on the method. `subscribe` and `issue_invoice` do
not return `Failure`.

THE FIVE READS AT THE BOTTOM MIRROR THE PAGES, and they exist because they did not. Until this block
was written, a PAGE was the only way to reach any of them: `views.py` next door draws the listing
(`paginate_invoices`), the detail (`show_invoice` + `payments_of`) and the report (`billing_report`),
and `invoices_of_customer` was reached from the orders operate page, to choose an invoice to bill
against. A read one surface can perform and the other cannot is a client that cannot ask a question
the other surface answers, which is what
`shared/tests/test_the_page_and_the_api_reach_one_usecase.py` measures. They go through the SAME use
cases the pages go through; nothing here re-implements a query.

That does NOT make billing writable. The section's four writes stay page-less by decision, argued in
`test_nav.py` and quoted in both parity nets: an invoice is raised by `orders.settle` and settled by
`pay_invoice`, and a form where a figure is retyped is the one thing accounting must not offer.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from snakeorm import SnakeUtc

from apps import wire
from apps.session import snake_session
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


_session = snake_session


def _int(request: Request, name: str, default: int) -> int:
    """A query-string integer, falling back rather than raising: the value comes from a URL.

    The same helper `orders/api.py` carries, and the same bargain: `?page=abc` is a mistake somebody
    typed, not a 500 on a listing that has nothing wrong with it. The use case clamps the number
    afterwards, so `?page=99` on a two-page listing answers page two.
    """
    try:
        return int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        return default


def _refusal(failure: usecases.Failure) -> Response:
    """The refusal as a response: its reason, with the status that reason maps to."""
    return Response({"detail": failure.reason}, status=FAILURE_STATUS[failure.reason])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def list_plans(request: Request) -> Response:
    """Every available plan."""
    return Response([plan_dict(p) for p in usecases.list_plans(_session(request))])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def subscriptions_of_user(request: Request, user_id: int) -> Response:
    """A user's subscriptions."""
    subs = usecases.subscriptions_of_user(_session(request), user_id)
    return Response([subscription_dict(s) for s in subs])


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def subscribe(request: Request) -> Response:
    """Subscribes a user to a plan (201)."""
    body = wire.json_object(request)
    sub = usecases.subscribe(
        _session(request), wire.integer(body["user_id"]), wire.integer(body["plan_id"])
    )
    return Response(subscription_dict(sub), status=201)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["DELETE"])
def cancel_subscription(request: Request, subscription_id: int) -> Response:
    """Cancels a subscription. 404 if it does not exist."""
    result = usecases.cancel_subscription(_session(request), subscription_id)
    if isinstance(result, usecases.Failure):
        return _refusal(result)
    return Response(status=204)


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def subscription_invoices(request: Request, subscription_id: int) -> Response:
    """GET: the subscription's invoices. POST `{amount_cents}`: issues an invoice (201)."""
    session = _session(request)
    if request.method == "POST":
        amount_cents = wire.integer(wire.json_object(request)["amount_cents"])
        invoice = usecases.issue_invoice(session, subscription_id, amount_cents)
        return Response(invoice_dict(invoice), status=201)
    invoices = usecases.invoices_of_subscription(session, subscription_id)
    return Response([invoice_dict(i) for i in invoices])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def unpaid_invoices(request: Request) -> Response:
    """Every invoice still awaiting payment."""
    invoices = usecases.unpaid_invoices(_session(request))
    return Response([invoice_dict(i) for i in invoices])


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def pay_invoice(request: Request, invoice_id: int) -> Response:
    """Charges an invoice `{method}` (creates the payment and marks it paid). 404 if the invoice does not exist."""
    method = wire.text(wire.json_object(request)["method"])
    result = usecases.pay_invoice(_session(request), invoice_id, method)
    if isinstance(result, usecases.Failure):
        return _refusal(result)
    return Response(payment_dict(result))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def paginate_invoices(request: Request) -> Response:
    """One page of invoices with what the pager needs, optionally narrowed to settled or open.

    TWO statements, whatever the page and whatever the filter: the count and the rows. That is one
    fewer than the stock pager pays, and the difference is the filter — this one is a BOOLEAN, so
    its options are a Python constant instead of a table that has to be read.

    `?paid=` is parsed by `parse_paid`, which is the SAME function the listing page uses, rather
    than by a `bool()` written here. A demo whose page posts `paid=open` and whose API wants
    `paid=false` has two vocabularies for one filter, and the client that reads a listing and posts
    the filter back is the one that finds out.
    """
    page = usecases.paginate_invoices(
        _session(request),
        paid=parse_paid(request.query_params.get("paid")),
        page=_int(request, "page", 1),
        per_page=_int(request, "per_page", 20),
    )
    return Response(invoice_page_dict(page))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def invoice(request: Request, invoice_id: int) -> Response:
    """One invoice with the chain behind it — subscription, plan and customer; 404 if it is gone.

    ONE statement for four rows: the three hops are to-one, so they are LEFT JOINs on the same
    SELECT. That is what the with-parties shape costs here and why a customer's invoices go out
    bare instead: that read pays for no joins, and a reader who opens ONE invoice wants the names
    rather than three more requests to look them up.
    """
    result = usecases.show_invoice(_session(request), invoice_id)
    if isinstance(result, usecases.Failure):
        return _refusal(result)
    return Response(invoice_with_parties_dict(result))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def invoice_payments(request: Request, invoice_id: int) -> Response:
    """The payments against an invoice, oldest first; 404 when the invoice does not exist.

    THE 404 COMES FROM `show_invoice` AND NOT FROM `payments_of`, which is deliberate on both sides.
    The use case does not check that the invoice exists — its caller on the detail PAGE has already
    fetched it and already had its `not_found`, so a check inside would be a third statement on
    every visit to learn what the caller knows. This endpoint has no such fetch behind it, so it
    makes the one the page already made: same two statements, same answer, and an unknown id gets a
    404 instead of an empty list that reads like "this invoice was never paid".
    """
    session = _session(request)
    found = usecases.show_invoice(session, invoice_id)
    if isinstance(found, usecases.Failure):
        return _refusal(found)
    payments = usecases.payments_of(session, invoice_id)
    return Response([payment_dict(payment) for payment in payments])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def invoices_of_customer(request: Request, user_id: int) -> Response:
    """Every invoice of a customer, across all their subscriptions, in ONE statement.

    `Invoice.subscription.user_id` is a two-hop navigation the emitter plans as a JOIN. Asking per
    subscription is the N+1 this replaces — invisible on the two-subscription customer the seed
    makes, and a round trip per row on anybody real.

    The rows come back BARE, so they are serialised bare. This read pays for no joins and pretending
    otherwise would raise while the response is being written.
    """
    invoices = usecases.invoices_of_customer(_session(request), user_id)
    return Response([invoice_dict(invoice) for invoice in invoices])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def billing_report(request: Request) -> Response:
    """The money report: FOUR statements, and not one of them grows with the number of rows.

    THE CLOCK IS READ HERE and passed down, exactly as `views.py::billing_report` does it for the
    page. A use case that called `now()` itself would answer differently on two runs and could not
    be tested; the handler is the layer that knows what 'now' means for this request.

    It cannot fail. Every figure on it is an aggregate, so a company with no invoices yet gets zeroes
    rather than a 404 — which is why there is no `Failure` branch here.
    """
    report = usecases.billing_report(
        _session(request),
        SnakeUtc.now(),
        minimum_cents=_int(request, "minimum_cents", 1),
    )
    return Response(billing_report_dict(report))
