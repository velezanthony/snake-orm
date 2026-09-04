"""Thin JSON API for the logistics domain (depots, sheets, dispatch and load): DRF over `shared`.

Thin views: they parse the request, call the use case with flat parameters and serialize with the
shared DTOs (data) or map the `Failure` to its status (error). Zero queries, zero `commit`. The
SnakeORM session is hung on `request.snake_session` by `SnakeSessionMiddleware`. DRF handles CSRF and
`@extend_schema` documents each operation at `/api/docs` (drf-spectacular).

FOUR ROUTES ANSWERING THE FOUR PAGES, which is what a BFF mirror means here: `/api/logistics/depots`
is `/logistics/list/` served as JSON, and so on down. The one that is spelled differently is the
reroute — a `PATCH` on the delivery's depot, because an API has verbs and a browser `<form>` has two.
Same use case underneath, and `test_the_page_and_the_api_reach_one_usecase.py` is what says so.

The numbers go out as NUMBERS: a slot as `9` and a distance as the float the engine computed. The
pages format those because a person reads a page; a client that received `"09:00"` would have to
parse a string back into an hour to do anything with it.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.logistics import usecases
from apps.session import snake_session
from shared.dto.logistics_dto import (
    delivery_sheet_dict,
    depot_dict,
    dispatch_entry_dict,
    slot_band_dict,
)
from shared.usecases.result import FAILURE_STATUS

_session = snake_session


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def depots(request: Request) -> Response:
    """Every depot with how many deliveries it carries and the units those come to."""
    summaries = usecases.list_depots(_session(request))
    return Response([depot_dict(summary) for summary in summaries])


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(methods=["PATCH"], responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PATCH"])
def delivery_sheet(request: Request, delivery_id: int) -> Response:
    """GET: one delivery's sheet. PATCH: reroutes it to the nearest depot and answers the new sheet.

    ONE ROUTE AND TWO VERBS, and the pairing is the point rather than a saving: the answer is the same
    document either way, so a client that reroutes does not have to fetch afterwards to find out what
    changed. It is also why the write takes no body — there is nothing to send. The depot is not the
    caller's choice; it is the answer to "which one is nearest", and the delivery already carries the
    coordinates that decide it.
    """
    session = _session(request)
    sheet = (
        usecases.reroute_delivery(session, delivery_id)
        if request.method == "PATCH"
        else usecases.delivery_sheet(session, delivery_id)
    )
    if isinstance(sheet, usecases.Failure):
        return Response({"detail": sheet.reason}, status=FAILURE_STATUS[sheet.reason])
    return Response(delivery_sheet_dict(sheet))


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def dispatch(request: Request) -> Response:
    """The soonest promises, each with the last day its van can leave to keep them."""
    entries = usecases.dispatch_board(_session(request))
    return Response([dispatch_entry_dict(entry) for entry in entries])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def load(request: Request) -> Response:
    """Every booking with the units booked in the band of hours around it."""
    bands = usecases.slot_load(_session(request))
    return Response([slot_band_dict(band) for band in bands])
