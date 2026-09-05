"""THIN SSR views of the billing domain: the three pages the money gets, and not the other two.

Django is a dumb shell here, exactly as it is for the blog, the pilot and orders. A view parses the
request, calls ONE function of its own layer — a view model from `apps.billing.viewmodels` — and
turns the answer into a response. It never touches a selector, never the session, and never builds a
dict by walking a relation: `invoice.subscription.plan.name` in a view is the same pair of queries
per row as it is in a template, moved one file up.

**THERE ARE NO WRITES IN THIS MODULE AND THAT IS THE DOMAIN'S STATEMENT.** Every other SSR domain of
the demo imports `usecases` beside `viewmodels`; this one does not, because there is nothing here to
call. An invoice is raised by `settle` over in orders and paid by `pay_invoice`, both of them
operations with a transaction around them, and a form that let somebody retype an amount would be a
demo of the one thing accounting software must never offer. So billing shows the READ side of money
— which is where the interesting queries were anyway: the listing flattens THREE to-one hops per row
without paying a query for any of them, and the report is three aggregates that do not grow with the
data.

**These pages need NO login, for the reason the pilot wrote down.** An invoice has an owner, so
unlike stock there would be something to compare a session against; what there is not is anything to
demonstrate by doing it. The blog's gate exists because hiding somebody else's post behind a 404 is
part of what the blog shows. Here the subject is a query, and a registration in front of it would
cost every reader of the demo a login to reach the page they came for while testing nothing about
the ORM.

`not_found` from the detail becomes `layout/error.html` with a 404. It is the only failure this
domain can produce: the listing and the report never return a `Failure` at all, because every figure
on them is an aggregate and "no invoices yet" is an answer rather than a missing page.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from snakeorm import SnakeUtc

from apps.session import snake_session
from apps.billing import viewmodels
from apps.billing.usecases import Failure
from apps.blog.guards import current_user

# How many invoices a page of the listing holds. Twenty, the same as every other listing in the
# demo: the pager is the thing being demonstrated, and it only demonstrates anything when the seeded
# data runs to more than one page.
_PER_PAGE = 20


_session = snake_session


def _not_found(request: HttpRequest) -> HttpResponse:
    """The 404 page, worded for this domain and pointing back at this domain's listing.

    The shell's error page takes its text from the context precisely so that a 404 in billing does
    not tell the reader that a stock pair is missing. One template, one layout, the words of
    whichever domain answered.
    """
    return render(
        request,
        "layout/error.html",
        {
            "user": current_user(request),
            "error_message": "That invoice does not exist. It may have been raised against a subscription that has since gone.",
            "back_href": reverse("billing_list"),
            "back_label": "Back to invoices",
        },
        status=404,
    )


def _int_or_none(raw: str | None) -> int | None:
    """An integer out of a query-string value; `None` when it is absent or not a number.

    Everything that reaches here came from a URL, which means it is a string somebody could have
    typed. `?page=abc` is a mistake, not a stack trace, and it is answered by falling back rather
    than by a 500 on a listing that has nothing wrong with it.
    """
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def invoice_list(request: HttpRequest) -> HttpResponse:
    """The paginated listing, optionally narrowed to settled or outstanding. TWO statements.

    Two, whatever page and whatever filter: the count and the page of rows. That is one fewer than
    the pilot pays, and the difference is worth naming on a page read as documentation — inventory
    filters by a TABLE of warehouses and has to read it, while this filter is a boolean whose three
    options are a Python constant.

    The filter value goes through to the view model AS THE STRING the form posted, and the parsing
    into "settled / outstanding / no filter at all" happens there, in `parse_paid`, once. A view that
    turned `?paid=` into a boolean first would be the second place that decision lives, on the second
    demo, which is the drift this layer was put in front of. What comes back is the normalised
    string, so `?paid=nonsense` redraws as "All invoices" rather than as a filter nothing matches.
    """
    page = viewmodels.invoice_list(
        _session(request),
        paid=request.GET.get("paid", ""),
        page=_int_or_none(request.GET.get("page")) or 1,
        per_page=_PER_PAGE,
    )
    context: dict[str, object] = {**page, "user": current_user(request)}
    return render(request, "billing/list/billing_list.html", context)


def invoice_detail(request: HttpRequest, invoice_id: int) -> HttpResponse:
    """One invoice in full: the chain behind it, its payments, and whether the two add up.

    The arithmetic that makes this page worth loading was done in the view model — the sum of the
    payments against the amount owed — because nothing in the schema forces an invoice's `paid` flag
    and its payments to agree. An invoice flagged settled with half of it paid is a row the database
    will hold forever, and this is the page that says so.
    """
    result = viewmodels.invoice_detail(_session(request), invoice_id)
    if isinstance(result, Failure):
        return _not_found(request)
    context: dict[str, object] = {**result, "user": current_user(request)}
    return render(request, "billing/detail/billing_detail.html", context)


def billing_report(request: HttpRequest) -> HttpResponse:
    """The money report: FOUR statements, and not one of them grows with the number of rows.

    The CLOCK is read here and passed down, rather than being asked for inside the report. A
    use case that called `now()` itself would answer differently on two runs and could not be
    tested; the view is the layer that knows what 'now' means for this request.

    It cannot fail. Every figure on it is an aggregate, so a company with no invoices yet gets a page
    of zeroes rather than a 404 — which is why there is no `Failure` branch here and why that is a
    property of the view model rather than something this view decided.
    """
    page = viewmodels.billing_report(_session(request), SnakeUtc.now())
    context: dict[str, object] = {**page, "user": current_user(request)}
    return render(request, "billing/report/billing_report.html", context)
