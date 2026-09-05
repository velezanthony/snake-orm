"""logistics view models: the four pages of the delivery domain — depots, sheet, dispatch and load.

The same four rules the other view models keep: go through the USE CASES and never a selector, return
a `TypedDict`, hand a `Failure` back untouched, and emit nothing but primitives so a template never
walks a relation.

WHAT THIS MODULE DOES **NOT** DO IS DECIDE ANYTHING, and that is the difference from every other view
model here. `logistics` is the first domain whose answers are read by two surfaces that both need the
same JUDGEMENT — is this delivery routed to the nearest depot, how many units are left loose after
the full boxes, which band of the day is the busiest — so those live in
`shared/usecases/logistics_usecases.py`, where both colours and both surfaces reach them. A view
model that re-derived one would be a second implementation of the domain, which is precisely what
`test_the_page_and_the_api_reach_one_usecase.py` exists to catch.

WHAT IS LEFT IS FORMATTING, and formatting is genuinely the page's. The engine answers a distance
with every digit a double has and a slot with the number 9; a template wants `4.3` and `09:00`, and
the JSON next door wants the numbers untouched — a client that received `"09:00"` would have to parse
a string back into an hour to do anything with it. That is the one place the two surfaces are
entitled to differ, and it is the last layer, which is exactly where the BFF design puts the
difference.
"""

from __future__ import annotations

from typing_extensions import TypedDict

from snakeorm import SnakeSession

from shared.models import BAND_HOURS, DISPATCH_LEAD_DAYS
from shared.usecases import logistics_usecases as usecases
from shared.usecases.result import Failure


class DepotRow(TypedDict):
    """One depot as a row: its code, its name and what is booked out of it."""

    code: str
    name: str
    deliveries: int
    units: int


class DepotListPage(TypedDict):
    """The landing page of the domain: every depot and the totals across them."""

    depots: list[DepotRow]
    depot_count: int
    total_units: int


class NearestRow(TypedDict):
    """One depot in a delivery's ranking: how far it is, and what it is to this delivery."""

    depot_id: int
    code: str
    name: str
    distance: str
    assigned: bool
    nearest: bool


class PackingSlip(TypedDict):
    """What a picker reads: the box size, the two roundings, and what is left loose."""

    units: int
    per_box: int
    boxes: int
    full_boxes: int
    loose_units: int


class DeliverySheetPage(TypedDict):
    """One delivery as a screen: where it goes, how it is packed, and whether it is routed right."""

    delivery_id: int
    reference: str
    depot: str
    packaging: str
    slot: str
    promised: str
    nearest: list[NearestRow]
    packing: PackingSlip
    is_routed_to_the_nearest: bool


class DispatchRow(TypedDict):
    """One delivery on the dispatch board: what it is promised for and when it has to leave."""

    delivery_id: int
    reference: str
    promised: str
    leave_by: str


class DispatchPage(TypedDict):
    """The board: the soonest promises, and the lead the whole domain counts back by."""

    rows: list[DispatchRow]
    lead_days: int


class SlotLoadRow(TypedDict):
    """One booking with the load of the band it sits in."""

    depot: str
    slot: str
    units: int
    band_units: int
    is_peak: bool


class SlotLoadPage(TypedDict):
    """The load page: every booking, its band, and how wide a band is."""

    rows: list[SlotLoadRow]
    band_hours: int
    peak_units: int


def _slot(hour: int) -> str:
    """An hour of the clock as a booking slot: `09:00`. The band is stated in hours, so this is one."""
    return f"{hour:02d}:00"


def _distance(value: float) -> str:
    """A distance rounded to one decimal, which is as much as a comparison between depots needs.

    The engine answers with every digit a double has. Printing them would claim a precision the
    figure has not got — these are degrees on a flat approximation, not metres — and would make two
    depots that are effectively the same distance away look like a ranking somebody should trust.
    """
    return f"{value:.1f}"


def depot_list(session: SnakeSession) -> DepotListPage:
    """Every depot with what is booked out of it, plus the totals across them.

    ONE statement whatever the number of depots: the two per-depot figures are correlated aggregates
    the engine computes, and the totals are added up over rows that have already arrived. A second
    statement to total four numbers would be a round trip to work out what is on the page.
    """
    depots: list[DepotRow] = [
        {
            "code": depot.code,
            "name": depot.name,
            "deliveries": depot.deliveries,
            "units": depot.units,
        }
        for depot in usecases.list_depots(session)
    ]
    return {
        "depots": depots,
        "depot_count": len(depots),
        "total_units": sum(depot["units"] for depot in depots),
    }


def delivery_sheet(
    session: SnakeSession, delivery_id: int
) -> DeliverySheetPage | Failure:
    """One delivery's sheet: the depot ranking, the packing slip and the routing verdict."""
    sheet = usecases.delivery_sheet(session, delivery_id)
    if isinstance(sheet, Failure):
        return sheet
    return _sheet_page(sheet)


def reroute(session: SnakeSession, delivery_id: int) -> DeliverySheetPage | Failure:
    """Reroutes a delivery to its nearest depot and gives back the sheet as it now reads.

    A WRITE in a view model, and the one in this package, so it is worth saying why it is not a
    breach of the rule. The rule is that a view model does not DECIDE anything — and this one does
    not: the use case picks the depot, writes the field and answers with the new sheet. What this
    adds is the formatting of that answer, which is the same job `delivery_sheet` above does for the
    same shape. The alternative was a view that wrote through the use case and then called the view
    model to read it back, which is the same three statements plus one that has just been answered.
    """
    sheet = usecases.reroute_delivery(session, delivery_id)
    if isinstance(sheet, Failure):
        return sheet
    return _sheet_page(sheet)


def dispatch_board(session: SnakeSession, *, limit: int = 20) -> DispatchPage:
    """The board: what is promised soonest and the last day its van can leave.

    Both dates arrive as calendar days from the selector, which normalises them where the driver
    hands them over — a computed date is typed on PostgreSQL and text on SQLite. Nothing is formatted
    here, and the page still goes through this layer because the LEAD is part of what it says: a
    column of dates with no statement of how far back they were counted is a column nobody can check.
    """
    return {
        "rows": [
            {
                "delivery_id": entry.delivery_id,
                "reference": entry.reference,
                "promised": entry.promised_on,
                "leave_by": entry.leave_by,
            }
            for entry in usecases.dispatch_board(session, limit=limit)
        ],
        "lead_days": DISPATCH_LEAD_DAYS,
    }


def slot_load(session: SnakeSession, *, limit: int = 40) -> SlotLoadPage:
    """Every booking with the load of the hours around it, and which band is the day's peak."""
    bands = usecases.slot_load(session, limit=limit)
    return {
        "rows": [
            {
                "depot": band.depot,
                "slot": _slot(band.slot_hour),
                "units": band.units,
                "band_units": band.band_units,
                "is_peak": band.is_peak,
            }
            for band in bands
        ],
        "band_hours": BAND_HOURS,
        "peak_units": max((band.band_units for band in bands), default=0),
    }


def _sheet_page(sheet: usecases.DeliverySheet) -> DeliverySheetPage:
    """The sheet formatted for a template. Written once because two operations answer with one shape.

    `delivery_sheet` reads it and `reroute` writes and then reads it, and they are the same screen —
    the second one is the first one after a button. Two formatters would be two screens that look
    alike until one of them is edited.
    """
    return {
        "delivery_id": sheet.delivery_id,
        "reference": sheet.reference,
        "depot": sheet.depot,
        "packaging": sheet.packaging,
        "slot": _slot(sheet.slot_hour),
        "promised": sheet.promised_on,
        "nearest": [
            {
                "depot_id": row.depot_id,
                "code": row.code,
                "name": row.name,
                "distance": _distance(row.distance),
                "assigned": row.assigned,
                "nearest": row.nearest,
            }
            for row in sheet.nearest
        ],
        "packing": {
            "units": sheet.packing.units,
            "per_box": sheet.packing.per_box,
            "boxes": sheet.packing.boxes,
            "full_boxes": sheet.packing.full_boxes,
            "loose_units": sheet.packing.loose_units,
        },
        "is_routed_to_the_nearest": sheet.is_routed_to_the_nearest,
    }
