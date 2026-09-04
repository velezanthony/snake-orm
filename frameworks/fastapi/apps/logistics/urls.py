"""Router of the logistics domain (depots, sheets, dispatch and load): a thin JSON API over the use cases.

Every endpoint calls the ASYNCHRONOUS use case with flat parameters and translates the result into
JSON (data -> DTO, `Failure` -> HTTPException). Zero queries, zero `commit` here.

THE SAME FOUR ROUTES the other two demos serve, which is what makes the three a mirror: the shape of
this file is `test_the_demos_serve_the_same_routes.py`'s subject, and the operation each route reaches
is `test_the_page_and_the_api_reach_one_usecase.py`'s. This demo has no HTML on purpose, so it appears
in the first comparison and is exempted from the second — which is a decision written down in that
file rather than a column of blanks.
"""

from __future__ import annotations

from fastapi import APIRouter

from apps.deps import SessionDep, http_error
from apps.logistics import usecases
from apps.logistics.usecases import Failure
from shared.dto.logistics_dto import (
    delivery_sheet_dict,
    depot_dict,
    dispatch_entry_dict,
    slot_band_dict,
)

router = APIRouter(prefix="/api/logistics", tags=["logistics"])


@router.get("/depots")
async def depots(session: SessionDep) -> list[dict[str, object]]:
    """Every depot with how many deliveries it carries and the units those come to."""
    return [depot_dict(summary) for summary in await usecases.list_depots(session)]


@router.get("/deliveries/{delivery_id}")
async def delivery_sheet(delivery_id: int, session: SessionDep) -> dict[str, object]:
    """One delivery's sheet: the depot ranking, the picking slip and the routing verdict.

    The ranking is a square root over a sum of squares that the engine computes, so only the three
    depots that win the comparison ever travel — the same statement the two synchronous demos run,
    because a `SnakeQuery` has no colour.
    """
    sheet = await usecases.delivery_sheet(session, delivery_id)
    if isinstance(sheet, Failure):
        raise http_error(sheet)
    return delivery_sheet_dict(sheet)


@router.patch("/deliveries/{delivery_id}")
async def reroute_delivery(delivery_id: int, session: SessionDep) -> dict[str, object]:
    """Reroute a delivery to the depot nearest its destination. 404 if there is no such delivery.

    NO BODY, and that is the design rather than an omission: the depot is not the caller's choice, it
    is the answer to "which one is nearest", and the delivery already carries the coordinates that
    decide it. What comes back is the sheet as it now reads.
    """
    sheet = await usecases.reroute_delivery(session, delivery_id)
    if isinstance(sheet, Failure):
        raise http_error(sheet)
    return delivery_sheet_dict(sheet)


@router.get("/dispatch")
async def dispatch(session: SessionDep) -> list[dict[str, object]]:
    """The soonest promises, each with the last day its van can leave to keep them."""
    return [
        dispatch_entry_dict(entry) for entry in await usecases.dispatch_board(session)
    ]


@router.get("/load")
async def load(session: SessionDep) -> list[dict[str, object]]:
    """Every booking with the units booked in the band of hours around it."""
    return [slot_band_dict(band) for band in await usecases.slot_load(session)]
