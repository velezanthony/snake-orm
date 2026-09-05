"""logistics domain use cases: depots, delivery sheets, dispatch boards and slot load, written once.

Five operations, and each one is a QUESTION a dispatcher asks out loud rather than a wrapper over a
selector. That distinction is the whole reason this domain exists — the coverage nets in
`shared/tests/` refuse a page invented to make a tally go up, and the only way past them is to grow a
domain that wanted the SQL anyway:

    list_depots       which depots are there, and how much is booked out of each
    delivery_sheet    where does this one go, and how many boxes does it need
    dispatch_board    what has to be on the road, and by when
    slot_load         how busy is each hour of a depot's day
    reroute_delivery  send it out of the depot that is actually nearest

The fifth is the only WRITE, and it is the one the second read makes obvious: the sheet ranks the
depots by distance and shows which one the delivery is assigned to, so a delivery sitting on the
second-nearest depot is a van driving further than it has to. That is a thing somebody fixes, and it
is a single field.

**THE ANSWERS ARE SHAPES AND NOT TUPLES, and this is the only domain where that was worth the extra
declarations.** Two surfaces read every one of these — a page and a JSON endpoint — and each answer
carries DECISIONS as well as figures: whether the assigned depot is the nearest one, how many units
are left loose after the full boxes, which band of the day is the busiest. A decision re-derived on
the other surface is a second implementation of the domain, which is precisely what
`test_the_page_and_the_api_reach_one_usecase.py` exists to catch. So the decision is made here, once,
and `shared/viewmodels/` and `shared/dto/` are both thin projections of the same object.

What is NOT decided here is FORMATTING, and the split is deliberate: a distance stays a `float` and a
slot stays an `int`, because a page wants `4.3` and `09:00` while a client wants the numbers. That is
the one place the two surfaces are entitled to differ, and it is the last layer — exactly where the
BFF design says the difference belongs.
"""

from __future__ import annotations

from dataclasses import dataclass

from snakeorm import SnakeSession

from shared.models import Delivery
from shared.selectors import logistics_selectors as selectors
from shared.services import logistics_services as services
from shared.usecases.result import Failure


@dataclass(frozen=True, slots=True)
class DepotSummary:
    """One depot and what is booked out of it."""

    code: str
    name: str
    deliveries: int
    units: int


@dataclass(frozen=True, slots=True)
class DepotDistance:
    """One depot in a delivery's ranking: how far it is, and what it is to this delivery.

    `assigned` and `nearest` are two different facts and the sheet is about the case where they
    disagree. Keeping them apart is what lets a page say "this is going to the second-nearest depot"
    instead of leaving a reader to compare a code against the first row by eye.
    """

    depot_id: int
    code: str
    name: str
    distance: float
    assigned: bool
    nearest: bool


@dataclass(frozen=True, slots=True)
class Packing:
    """A picking slip: the box size, the two roundings, and what is left over.

    `loose_units` is `units - full_boxes * per_box`, computed here rather than in SQL. Both figures
    have already arrived, so pushing the subtraction down would add a round trip to work out
    something that is on the page — the rule `orders_viewmodels` and `billing_viewmodels` both have
    written down. What could NOT be done up here is the rounding itself: `units / per_box` is integer
    division on two of the three engines, and the cast that fixes it belongs with the statement.
    """

    units: int
    per_box: int
    boxes: int
    full_boxes: int
    loose_units: int


@dataclass(frozen=True, slots=True)
class DeliverySheet:
    """One delivery as an answer: where it goes, how it is packed, and whether it is routed right."""

    delivery_id: int
    reference: str
    depot: str
    packaging: str
    slot_hour: int
    promised_on: str
    nearest: tuple[DepotDistance, ...]
    packing: Packing
    is_routed_to_the_nearest: bool


@dataclass(frozen=True, slots=True)
class DispatchEntry:
    """One line of the dispatch board: what is promised, and the last day the van can leave.

    Both dates are calendar DAYS and they arrive that way from the selector, which normalises them at
    the seam where the driver hands them over — a computed date is typed on PostgreSQL and text on
    SQLite, and neither surface should have to know that.
    """

    delivery_id: int
    reference: str
    promised_on: str
    leave_by: str


@dataclass(frozen=True, slots=True)
class SlotBand:
    """One booking with the load of the hours around it, and whether that band is the day's peak."""

    depot: str
    slot_hour: int
    units: int
    band_units: int
    is_peak: bool


def list_depots(session: SnakeSession) -> list[DepotSummary]:
    """Every depot with how many deliveries it carries and the units those come to."""
    return [
        DepotSummary(code=code, name=name, deliveries=deliveries, units=units)
        for code, name, deliveries, units in selectors.depot_rows(session)
    ]


def delivery_sheet(session: SnakeSession, delivery_id: int) -> DeliverySheet | Failure:
    """One delivery, the depots nearest to it, and its packing figures. `not_found` if there is none.

    THREE STATEMENTS AND NOT ONE, and that is a decision rather than a shortcut. The delivery and its
    packing slip are about ONE row; the ranking is about the depots table, correlated to that row's
    coordinates. Folding them together would join every depot onto one delivery and carry the same
    delivery columns down every line — the shape a report grows when somebody counts statements
    instead of reading them.

    The refusal comes first because the other two reads need the row's coordinates: without the
    delivery there is no point to measure from, and a ranking of depots around nothing is not a
    thinner answer, it is a different question.
    """
    found = selectors.find_delivery(session, delivery_id)
    if found is None:
        return Failure("not_found")
    packing = selectors.packing_slip(session, delivery_id)
    if packing is None:
        return Failure("not_found")
    ranking = selectors.nearest_depots(session, found.latitude, found.longitude)
    return _sheet(found, ranking, packing)


def dispatch_board(session: SnakeSession, *, limit: int = 20) -> list[DispatchEntry]:
    """The soonest promises, each with the last day its van can leave to keep them."""
    return [
        DispatchEntry(
            delivery_id=delivery_id,
            reference=reference,
            promised_on=promised_on,
            leave_by=leave_by,
        )
        for delivery_id, reference, promised_on, leave_by in selectors.dispatch_rows(
            session, limit=limit
        )
    ]


def slot_load(session: SnakeSession, *, limit: int = 40) -> list[SlotBand]:
    """Each booking with everything booked within the same hours of the same depot."""
    return _bands(selectors.slot_load_rows(session, limit=limit))


def reroute_delivery(
    session: SnakeSession, delivery_id: int
) -> DeliverySheet | Failure:
    """Moves a delivery to the depot nearest its destination. `not_found` if there is no such one.

    IDEMPOTENT, and that matters here for the reason it mattered to tagging: this is a button on a
    page, and a button on a page gets pressed twice. A delivery already sitting on its nearest depot
    is rerouted to the same depot, which writes the value it already had and answers the same sheet —
    rather than refusing, which would tell somebody who did exactly the right thing that they failed.

    IT ANSWERS WITH THE SHEET, not with a bare acknowledgement, and that is what makes the write
    honest on both surfaces: what a caller wants to know after rerouting is what the ranking looks
    like NOW.

    AND IT RE-READS TO BUILD IT, which is not laziness. The row loaded above came with its depot
    already joined, so after the field changes the instance still carries the OLD depot object — the
    sheet built from it would print the code the delivery has just stopped being routed to. This ORM
    keeps no identity map and refreshes nothing behind the caller's back, on purpose; the price of
    that honesty is that a write invalidates what was loaded before it, and the caller is the one
    that has to say so.
    """
    found = selectors.find_delivery(session, delivery_id)
    if found is None:
        return Failure("not_found")
    ranking = selectors.nearest_depots(
        session, found.latitude, found.longitude, limit=1
    )
    if not ranking:
        return Failure("not_found")
    services.route_to(session, found, ranking[0][0])
    session.commit()
    return delivery_sheet(session, delivery_id)


def _sheet(
    delivery: Delivery,
    ranking: list[tuple[int, str, str, float]],
    packing: tuple[int, int, int, int],
) -> DeliverySheet:
    """The sheet built out of what the three reads answered. Colourless: it runs no statement.

    A plain function and not a method, and shared by both colours through
    `shared/aio/logistics_usecases.py`. That is the whole trick of this package: everything that CAN
    be written once is, and what is left over per colour is the awaiting.
    """
    units, per_box, boxes, full = packing
    nearest = tuple(
        DepotDistance(
            depot_id=depot_id,
            code=code,
            name=name,
            distance=distance,
            assigned=depot_id == delivery.depot_id,
            nearest=index == 0,
        )
        for index, (depot_id, code, name, distance) in enumerate(ranking)
    )
    return DeliverySheet(
        delivery_id=delivery.id,
        reference=delivery.reference,
        depot=delivery.depot.code,
        packaging=delivery.packaging.name,
        slot_hour=delivery.slot_hour,
        promised_on=delivery.promised_at.date().isoformat(),
        nearest=nearest,
        packing=Packing(
            units=units,
            per_box=per_box,
            boxes=boxes,
            full_boxes=full,
            loose_units=units - full * per_box,
        ),
        is_routed_to_the_nearest=any(row.assigned and row.nearest for row in nearest),
    )


def _bands(rows: list[tuple[str, int, int, int]]) -> list[SlotBand]:
    """The load rows with the peak marked. Colourless, and shared by both colours for that reason.

    The peak is a property of THIS PAGE — the busiest band among the ones being shown — so it is
    computed over rows that have already arrived. Asking the engine for it would be a second
    statement answering a question about the first one's output.
    """
    peak = max((band for _, _, _, band in rows), default=0)
    return [
        SlotBand(
            depot=code,
            slot_hour=hour,
            units=units,
            band_units=band,
            is_peak=band == peak and peak > 0,
        )
        for code, hour, units, band in rows
    ]
