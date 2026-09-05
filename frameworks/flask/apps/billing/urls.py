"""SSR routes of the billing domain: THREE pages, and the two that are missing are the statement.

There is no `create`, no `update` and no `delete` here, and that is the design rather than a page
half-written. `inventory` and `orders` get the whole CRUD taxonomy because a stock level is corrected
and an order is edited; an invoice is neither. It is RAISED by `settle` and paid by a payment, and a
form that let somebody retype an amount would be a demo of the one thing accounting software must
never offer. `shared/tests/test_nav.py` asserts the absence, so the three pages cannot quietly become
five.

What is left is the READ side of money, which is where the interesting queries were anyway: the one
listing in these demos that flattens THREE to-one hops per row (`invoice -> subscription -> plan` and
`-> user`) without paying a query for any of them, a detail page whose subject is an arithmetic the
schema does not enforce, and a report built out of `annotate`, `GROUP BY`/`HAVING` and a set
subtraction between the two.

**The blueprint here is `billing` and the JSON one next door is now `billing-api`.** Two blueprints
cannot share a `url_for` name, and the API held the plain one for as long as this domain had no pages
to collide with it — which is exactly the story `inventory` already went through. The convention it
settled is the one applied here: a plain name is the pages, the `-api` suffix is the JSON. Renaming
the API rather than decorating the pages is what keeps `url_for('billing.invoice_detail')` reading
like every other page endpoint in the demo.

**These pages need NO login**, the same call the inventory and the orders pages make. An invoice
names a customer but is not owned by whoever is looking at it — this is the finance desk's screen,
not the customer's — so a login step would gate the pages without testing one thing about the ORM.
The demo gates what has an owner.

The views are THIN in the sense the whole demo means by it: they read the request, call the layer
below with FLAT parameters and translate the answer. There is no POST in this module at all, so
every one of them calls `viewmodels` and none calls `usecases`.
"""

from __future__ import annotations

from flask import Blueprint, g, render_template, request
from flask.typing import ResponseReturnValue

from snakeorm import SnakeUtc

from apps.billing import viewmodels
from apps.billing.usecases import Failure

# The domain's PAGES. The JSON side is `billing-api` in `api.py`, which is where the suffix belongs.
billing = Blueprint("billing", __name__, url_prefix="/billing")

# A resource `Failure` to its HTTP code. `not_found` is the ONLY reason that can reach this module:
# there is no form here to bounce `missing_fields` back to and no operation to refuse with a
# `conflict`, which is what a domain with no writes looks like from the routing layer.
_STATUS_BY_REASON = {"not_found": 404}


def _render_failure(failure: Failure) -> tuple[str, int]:
    """Translate a resource `Failure` into the error page with the status its reason maps to."""
    return render_template("layout/error.html"), _STATUS_BY_REASON[failure.reason]


def _int_arg(name: str, default: int) -> int:
    """One integer out of the query string, falling back rather than raising.

    It arrives from a URL somebody may have typed, so `page=abc` is a page that does not exist and
    not a stack trace. What a page number MEANS is not clamped here: the use case owns that, because
    only it knows how many pages there are.
    """
    return request.args.get(name, default=default, type=int) or default


@billing.get("/list")
def invoice_list() -> ResponseReturnValue:
    """The invoice listing: a real page of rows, the settlement filter and a pager. TWO statements.

    Two and not the inventory's three, and the missing one is the filter's own query: this filter is
    a BOOLEAN, so its three options are a Python constant, while the stock listing has to read the
    table of warehouses its `<select>` is made of. Neither of the two grows with the number of rows,
    which is what makes the page's cost flat over a history that only gets longer.

    `?paid=` is read by `viewmodels.parse_paid` rather than by an `if` written here, which is the
    same rule `?state=` follows one domain over: an unrecognised value means NO filter, because a
    typo in a hand-edited URL is not a 500, and because two demos writing that reading twice is how
    they end up disagreeing about what `paid=maybe` does.

    It cannot fail. An empty page is an answer, and there is no id in the URL to be wrong about.
    """
    page = viewmodels.invoice_list(
        g.session,
        paid=request.args.get("paid", ""),
        page=_int_arg("page", 1),
    )
    return render_template("billing/list/billing_list.html", **page)


@billing.get("/detail/<int:invoice_id>")
def invoice_detail(invoice_id: int) -> ResponseReturnValue:
    """One invoice, its chain and every payment against it. TWO statements. 404 if it is not there.

    The page exists for the subtraction on it. An invoice carries a `paid` flag AND a list of partial
    payments, and nothing in the schema forces the two to agree — so an invoice marked settled whose
    payments fall short is a row the database will hold forever and only a page like this one shows.
    `is_short` is computed in the view model and not by a template comparing two formatted strings.
    """
    page = viewmodels.invoice_detail(g.session, invoice_id)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template("billing/detail/billing_detail.html", **page)


@billing.get("/report")
def billing_report() -> ResponseReturnValue:
    """The money report: FOUR statements, none of which grows with the data.

    It reads nothing off the query string, the same call the other two reports make: `minimum_cents`
    changes what "has invoiced money" MEANS, and a definition that can be dialled from a URL is a
    number two people can quote from the same page and disagree about. The page prints the threshold
    it applied instead, which is what makes its figures reproducible.

    No `Failure` is possible: every figure is an aggregate, and a company with no invoices yet is an
    answer rather than a missing page.
    """
    page = viewmodels.billing_report(g.session, SnakeUtc.now())
    return render_template("billing/report/billing_report.html", **page)
