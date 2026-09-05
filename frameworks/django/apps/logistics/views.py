"""THIN SSR views of the logistics domain: the four pages of the delivery graph.

Django is a dumb shell here, the same as it is for the blog, inventory, orders, billing and taxonomy.
A view parses the request, calls ONE function of its own layer — a view model from
`apps.logistics.viewmodels` — and turns the answer into a response. It never touches a selector,
never the session, and never walks a relation.

**THE SHEET IS THE PAGE THIS DOMAIN EXISTS FOR.** It ranks the depots by their distance to a
delivery's destination — a square root over a sum of squares, computed by the engine so that only the
three that win travel — and says whether the depot the delivery is actually booked out of is the one
that won. When it is not, the page has a button, and the button is the domain's only write.

**THE DETAIL PAGE TAKES A POST**, which is the one place here where the page taxonomy bends, and it
bends the way `taxonomy` already bent it: a browser `<form>` emits only GET and POST, so rerouting is
a POST to the page that shows the ranking rather than a `PATCH` on a delivery resource the way the
API does it.

**No login.** A depot has no owner and neither has a delivery — this is an operations screen, not
somebody's account — so a gate here would cost every reader of the demo a registration to reach the
page they came for while testing nothing about the ORM. The demo gates what has an owner, which is
the call `taxonomy` made before this one.

`not_found` becomes `layout/error.html` with a 404, worded for this domain: the shell's error page
takes its text from the context precisely so a 404 in logistics does not tell the reader a tag is
missing.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from apps.blog.guards import current_user
from apps.logistics import viewmodels
from apps.logistics.usecases import Failure
from apps.session import snake_session

_session = snake_session


def _not_found(request: HttpRequest) -> HttpResponse:
    """The 404 page, worded for this domain and pointing back at this domain's listing."""
    return render(
        request,
        "layout/error.html",
        {
            "user": current_user(request),
            "title": "Delivery not found",
            "message": "There is no delivery with that reference.",
            "back_href": reverse("logistics_list"),
            "back_label": "Back to the depots",
        },
        status=404,
    )


def depot_list(request: HttpRequest) -> HttpResponse:
    """Every depot with what is booked out of it. ONE statement, whatever the number of depots.

    The two figures per depot are correlated aggregates the engine computes; the totals across depots
    are added up in the view model over rows that have already arrived. Walking `depot.deliveries`
    here would be the same page at one query per depot — the N+1 inside the renderer that this layer
    exists to keep out.
    """
    return render(
        request,
        "logistics/list/logistics_list.html",
        {**viewmodels.depot_list(_session(request)), "user": current_user(request)},
    )


def delivery_sheet(request: HttpRequest, delivery_id: int) -> HttpResponse:
    """GET: one delivery's sheet. POST: reroutes it to its nearest depot, then redraws.

    The POST goes through the same view model as the GET and comes back as the same shape, which is
    what makes the button honest: what a person sees after pressing it is the sheet as it now reads,
    with `assigned` and `nearest` on the same row. Redirecting to the GET would be one more statement
    to answer a question that has just been answered.
    """
    session = _session(request)
    user = current_user(request)
    page = (
        viewmodels.reroute(session, delivery_id)
        if request.method == "POST"
        else viewmodels.delivery_sheet(session, delivery_id)
    )
    if isinstance(page, Failure):
        return _not_found(request)
    return render(
        request, "logistics/detail/logistics_detail.html", {**page, "user": user}
    )


def dispatch_board(request: HttpRequest) -> HttpResponse:
    """What is promised soonest, and the last day each van can leave to keep the promise.

    The deadline is the promise shifted BACKWARD by the lead, computed by the engine. It is the
    direction `billing` never needed: a due date only ever moves forward.
    """
    return render(
        request,
        "logistics/dispatch/logistics_dispatch.html",
        {**viewmodels.dispatch_board(_session(request)), "user": current_user(request)},
    )


def slot_load(request: HttpRequest) -> HttpResponse:
    """How busy each hour of each depot's day is: the units booked in the band around every slot.

    The band is a `RANGE` frame and not a `ROWS` one, which is what makes the page mean anything:
    two deliveries booked into the same hour are ONE band and read the same figure, because the span
    is counted in hours rather than in neighbouring rows.
    """
    return render(
        request,
        "logistics/load/logistics_load.html",
        {**viewmodels.slot_load(_session(request)), "user": current_user(request)},
    )
