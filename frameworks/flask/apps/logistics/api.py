"""JSON API of the logistics domain (depots, sheets, dispatch and load): thin endpoints over `shared`.

Every endpoint parses the request, calls the use case with flat parameters and translates the result
into JSON (data -> DTO, `Failure` -> `abort(status)`). The ORM session is opened by the blog's
`before_app_request` hook in `g.session`.

FOUR ROUTES ANSWERING THE FOUR PAGES, which is what a BFF mirror means here: `/api/logistics/depots`
is `/logistics/list` served as JSON, and so on down. The one spelled differently is the reroute — a
`PATCH` on the delivery, because an API has verbs and a browser `<form>` has two. Same use case
underneath, and `test_the_page_and_the_api_reach_one_usecase.py` is what says so.

The numbers go out as NUMBERS: a slot as `9` and a distance as the float the engine computed. The
pages format those because a person reads a page.
"""

from __future__ import annotations

from flask import abort, g, jsonify
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from apps.logistics import usecases
from shared.dto.logistics_dto import (
    delivery_sheet_dict,
    depot_dict,
    dispatch_entry_dict,
    slot_band_dict,
)
from shared.usecases.result import FAILURE_STATUS

logistics = Blueprint(
    # `-api` because the plain `logistics` belongs to the PAGES in `urls.py`, the same split
    # `blog`/`blog-api`, `inventory`/`inventory-api`, `billing`/`billing-api` and
    # `taxonomy`/`taxonomy-api` already make.
    "logistics-api",
    __name__,
    url_prefix="/api/logistics",
    description="Logistics: depots, delivery sheets, dispatch and slot load",
)


@logistics.get("/depots")
def depots() -> ResponseReturnValue:
    """Every depot with how many deliveries it carries and the units those come to."""
    return jsonify([depot_dict(summary) for summary in usecases.list_depots(g.session)])


@logistics.get("/deliveries/<int:delivery_id>")
def delivery_sheet(delivery_id: int) -> ResponseReturnValue:
    """One delivery's sheet: the depot ranking, the picking slip and the routing verdict. 404 if none."""
    sheet = usecases.delivery_sheet(g.session, delivery_id)
    if isinstance(sheet, usecases.Failure):
        abort(FAILURE_STATUS[sheet.reason])
    return jsonify(delivery_sheet_dict(sheet))


@logistics.patch("/deliveries/<int:delivery_id>")
def reroute_delivery(delivery_id: int) -> ResponseReturnValue:
    """Reroute a delivery to the depot nearest its destination. 404 if there is no such delivery.

    NO BODY, and that is the design rather than an omission: the depot is not the caller's choice, it
    is the answer to "which one is nearest", and the delivery already carries the coordinates that
    decide it. What comes back is the sheet as it now reads, so a client that reroutes does not have
    to fetch afterwards to find out what changed.
    """
    sheet = usecases.reroute_delivery(g.session, delivery_id)
    if isinstance(sheet, usecases.Failure):
        abort(FAILURE_STATUS[sheet.reason])
    return jsonify(delivery_sheet_dict(sheet))


@logistics.get("/dispatch")
def dispatch() -> ResponseReturnValue:
    """The soonest promises, each with the last day its van can leave to keep them."""
    return jsonify(
        [dispatch_entry_dict(entry) for entry in usecases.dispatch_board(g.session)]
    )


@logistics.get("/load")
def load() -> ResponseReturnValue:
    """Every booking with the units booked in the band of hours around it."""
    return jsonify([slot_band_dict(band) for band in usecases.slot_load(g.session)])
