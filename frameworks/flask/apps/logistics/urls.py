"""SSR routes of the logistics domain: FOUR pages over depots, distances, packing and slot load.

**The blueprint here is `logistics` and the JSON one next door is `logistics-api`.** Two blueprints
cannot share a `url_for` name, and the convention `inventory`, `billing` and `taxonomy` settled is the
one applied here: a plain name is the pages, the `-api` suffix is the JSON. This domain was born with
both, so it never had the collision the other three walked into — the convention is applied because
it is the convention, not because something broke.

FOUR AND NOT FIVE. There is no page to book a delivery and none to open a depot, and that is the
domain's statement rather than two forms nobody wrote: a delivery is booked by whatever system takes
the customer's order, a depot is a building somebody surveyed, and a box size is a fact about
cardboard. What a dispatcher DOES is move a delivery to the right depot, and that is the one write.

THE SHEET IS THE PAGE THE DOMAIN EXISTS FOR. It ranks the depots by distance to a delivery's
destination — a square root over a sum of squares, computed by the engine so only the three that win
travel — and says whether the depot it is actually booked out of is the one that won.

THE SHEET TAKES A POST, and it is the one place here where the page taxonomy bends. A browser `<form>`
emits only GET and POST, so rerouting is a POST to the page that shows the ranking rather than a
`PATCH` on a delivery resource the way the API does it.

**No login**: a depot has no owner and neither has a delivery. This is an operations screen, so a gate
would cost every reader a registration to reach the page they came for while testing nothing about
the ORM. The demo gates what has an owner.

These routes carry NO trailing slash, which is the mirror convention: Django's `APPEND_SLASH` keeps
one and Flask deliberately does not.
"""

from __future__ import annotations

from flask import Blueprint, g, render_template, request, url_for
from flask.typing import ResponseReturnValue

from apps.logistics import viewmodels
from apps.logistics.usecases import Failure

# The domain's PAGES. The JSON side is `logistics-api` in `api.py`, which is where the suffix belongs.
logistics = Blueprint("logistics", __name__, url_prefix="/logistics")


def _not_found() -> tuple[str, int]:
    """The 404 page, worded for this domain and pointing back at this domain's listing."""
    return render_template(
        "layout/error.html",
        title="Delivery not found",
        message="There is no delivery with that reference.",
        back_href=url_for("logistics.depot_list"),
        back_label="Back to the depots",
    ), 404


@logistics.get("/list")
def depot_list() -> ResponseReturnValue:
    """Every depot with what is booked out of it. ONE statement, whatever the number of depots.

    The two figures per depot are correlated aggregates the engine computes, and the totals across
    them are added up in the view model over rows that have already arrived. Walking
    `depot.deliveries` from this page instead would paint the same thing at one query per depot — an
    N+1 inside the renderer, which is the one layer no test counts.
    """
    return render_template(
        "logistics/list/logistics_list.html", **viewmodels.depot_list(g.session)
    )


@logistics.route("/detail/<int:delivery_id>", methods=["GET", "POST"])
def delivery_sheet(delivery_id: int) -> ResponseReturnValue:
    """GET: one delivery's sheet. POST: reroutes it to its nearest depot, then redraws.

    The POST goes through the same view model as the GET and comes back as the same shape, which is
    what makes the button honest: what a person sees after pressing it is the sheet as it now reads,
    with `assigned` and `nearest` on the same row. Redirecting to the GET would be one more statement
    to answer a question that has just been answered.
    """
    page = (
        viewmodels.reroute(g.session, delivery_id)
        if request.method == "POST"
        else viewmodels.delivery_sheet(g.session, delivery_id)
    )
    if isinstance(page, Failure):
        return _not_found()
    return render_template("logistics/detail/logistics_detail.html", **page)


@logistics.get("/dispatch")
def dispatch_board() -> ResponseReturnValue:
    """What is promised soonest, and the last day each van can leave to keep the promise.

    The deadline is the promise shifted BACKWARD by the lead, computed by the engine. It is the
    direction `billing` never needed: a due date only ever moves forward.
    """
    return render_template(
        "logistics/dispatch/logistics_dispatch.html",
        **viewmodels.dispatch_board(g.session),
    )


@logistics.get("/load")
def slot_load() -> ResponseReturnValue:
    """How busy each hour of each depot's day is: the units booked in the band around every slot.

    The band is a `RANGE` frame and not a `ROWS` one, which is what makes the page mean anything:
    two deliveries booked into the same hour are ONE band and read the same figure, because the span
    is counted in hours rather than in neighbouring rows.
    """
    return render_template(
        "logistics/load/logistics_load.html", **viewmodels.slot_load(g.session)
    )
