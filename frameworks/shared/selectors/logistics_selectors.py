"""logistics domain — SELECTORS: depots, distances, packing slips, dispatch dates and slot load.

Every framework re-exports them from `apps/logistics/selectors.py`.

Each read comes in TWO pieces, as the rest of this package does it: the FRAGMENT builds a
`SnakeQuery` — or, for a projection, the columns it goes with — and runs nothing; the EXECUTOR takes
a session and runs it. Only the executor has a colour, so the SQL is written once and both the
synchronous demos and the asynchronous one in `shared/aio/` run the very same statement.

FOUR QUESTIONS LIVE HERE, and each one is the reason a piece of SQL exists rather than the other way
round. They are worth naming together, because read apart they look like four unrelated functions:

    where does it go?    the distance from a delivery to every depot        -> SQRT over POWERs
    how is it packed?    boxes to label, and boxes that stay shut           -> CEIL and FLOOR
    when must it leave?  the promise, moved BACKWARD by the lead            -> a date shifted back
    how busy is that?    the units booked in the HOURS around a slot        -> a RANGE frame

THE TWO ROUNDING QUESTIONS ARE NOT ONE, and that is the whole reason both are here. `ceil` says how
many boxes get a label printed and `floor` how many go on the van without anybody opening them; they
part company exactly when there is a remainder, and the remainder is the loose picking a warehouse
worker has to do by hand. A slip that only printed one of the two would be a slip somebody has to do
arithmetic on.

AND NEITHER OF THEM TOUCHES MONEY. That is the objection this domain had to clear before it could
exist: the repository's rule is that money is formatted from exact integer cents in
`billing_viewmodels.money_from_cents` and never rounded inside SQL, because rounding there throws
away the exactness integer cents exist to keep. Units in a box are not money — they are a COUNT, and
a count rounded up is the honest answer to "how many boxes do I need".
"""

from __future__ import annotations

from datetime import datetime

from snakeorm import (
    SnakeDatePart,
    SnakeQuery,
    SnakeSession,
    SnakeUtc,
    SnakeValue,
    snake_cast,
    snake_ceil,
    snake_coalesce,
    snake_date_sub,
    snake_floor,
    snake_following,
    snake_power,
    snake_preceding,
    snake_range,
    snake_sqrt,
    sum_,
)

from shared.models import BAND_HOURS, DISPATCH_LEAD_DAYS, Delivery, Depot

# How many depots the "where does this go" screen ranks. Three and not all of them: the question is
# which depot the van should leave from, and a ranking long enough to scroll has stopped answering it.
NEAREST_DEPOTS = 3


# --- where does it go: the distance ---------------------------------------------------------------


def distance_to(latitude: float, longitude: float) -> SnakeValue[float]:
    """FRAGMENT: how far each depot is from one point. NOT executed.

    `SQRT(POWER(dlat, 2) + POWER(dlon, 2))`, computed by the ENGINE, which is what makes it usable as
    an ORDER BY key: the ranking happens where the rows are, and only the three that win travel.
    Pulling every depot into Python to sort them there would be the same answer at the cost of the
    whole table, and it is the trade this layer exists to refuse.

    THE SQUARE ROOT IS NOT NEEDED TO ORDER and it is taken anyway, on purpose. Squared distance ranks
    identically — it is monotone — so a version without it would be one function call cheaper and
    would answer the same. What it would NOT do is give the page a number to PRINT: "4.3" next to a
    depot is a distance a reader can compare with the next row, and "18.5" is a square nobody asked
    for. The figure is part of the answer, not a step towards it.

    The point travels as PARAMETERS, like every value in this ORM. A delivery's coordinates are data
    that arrived with the row, and a formula built by pasting them into the string would be the one
    door this project keeps shut.
    """
    return snake_sqrt(
        snake_power(Depot.latitude - latitude, 2.0)
        + snake_power(Depot.longitude - longitude, 2.0)
    )


def depots_by_distance(
    latitude: float, longitude: float, *, limit: int = NEAREST_DEPOTS
) -> SnakeQuery[Depot]:
    """FRAGMENT: the depots nearest to a point, closest first. NOT executed.

    `code` breaks the tie, and it is not decoration: two depots equidistant from an address is a
    thing that happens on a grid of round coordinates, and without a second key the winner is
    whatever order the engine felt like — which makes the same page answer differently on two
    engines and the reroute below pick a different depot on each run.
    """
    return (
        SnakeQuery(Depot)
        .order_by(distance_to(latitude, longitude).asc(), Depot.code.asc())
        .limit(limit)
    )


def nearest_depots(
    session: SnakeSession,
    latitude: float,
    longitude: float,
    *,
    limit: int = NEAREST_DEPOTS,
) -> list[tuple[int, str, str, float]]:
    """The nearest depots to a point: `(id, code, name, distance)`, closest first."""
    query = depots_by_distance(latitude, longitude, limit=limit)
    rows = session.select(
        query, Depot.id, Depot.code, Depot.name, distance_to(latitude, longitude)
    )
    return [(id_, code, name, float(distance)) for id_, code, name, distance in rows]


# --- the depots themselves ------------------------------------------------------------------------


def depots() -> SnakeQuery[Depot]:
    """FRAGMENT: every depot, by code. NOT executed."""
    return SnakeQuery(Depot).order_by(Depot.code.asc())


def depot_columns() -> tuple[
    SnakeValue[str], SnakeValue[str], SnakeValue[int], SnakeValue[int]
]:
    """FRAGMENT: the four values the depot listing projects, in ONE statement.

    The two figures are CORRELATED aggregates over the depot's own deliveries, so the listing is one
    statement whatever the number of depots. Walking `depot.deliveries` in a template would be the
    same page at a query per row, which is the N+1 this layer exists to keep out of a renderer.

    `COALESCE` on the sum and not on the count, and the asymmetry is the engines': `COUNT` over no
    rows is `0` everywhere and `SUM` over no rows is `NULL` everywhere. A depot with nothing booked
    holds zero units, not an unknown number of them, and saying so inside the statement is what keeps
    the column non-nullable all the way to the page.
    """
    return (
        Depot.code,
        Depot.name,
        Depot.deliveries.count(),
        snake_coalesce(Depot.deliveries.sum_(Delivery.units), 0),
    )


def depot_rows(session: SnakeSession) -> list[tuple[str, str, int, int]]:
    """Every depot with how many deliveries it carries and how many units those come to."""
    rows = session.select(depots(), *depot_columns())
    return [
        (code, name, int(deliveries), int(units))
        for code, name, deliveries, units in rows
    ]


# --- one delivery ---------------------------------------------------------------------------------


def delivery(delivery_id: int) -> SnakeQuery[Delivery]:
    """FRAGMENT: ONE delivery with its depot and its packaging loaded. NOT executed.

    The `include` is the JOIN. The sheet prints the assigned depot's code beside the ranking of the
    nearest ones, so the row is needed anyway; fetching it here is one statement instead of three.
    """
    return (
        SnakeQuery(Delivery)
        .filter(Delivery.id == delivery_id)
        .include(Delivery.depot, Delivery.packaging)
    )


def find_delivery(session: SnakeSession, delivery_id: int) -> Delivery | None:
    """One delivery with its depot and packaging, or `None` if there is no such reference."""
    return session.first(delivery(delivery_id))


# --- how is it packed: the picking slip -----------------------------------------------------------


def boxes_needed() -> SnakeValue[float]:
    """FRAGMENT: how many boxes this delivery needs — `units / per_box`, rounded UP. NOT executed.

    THE CAST IS NOT OPTIONAL and it is the same trap `billing.collected_fraction` documents. Both
    sides are integers, so `units / per_box` is INTEGER division on PostgreSQL and SQLite: nineteen
    units of a forty-eight-unit box would answer `0`, `CEIL(0)` is `0`, and the slip would say a
    delivery needs no boxes at all. Naming the division as a real one is what makes the rounding mean
    anything.

    A FLOAT COMES BACK, on all three, and that is the ORM's own measurement rather than a surprise:
    `snake_ceil` keeps the type of its argument because `CEIL(1.2)` answers `2` on PostgreSQL and
    MySQL and `2.0` on SQLite, and declaring `int` would be false on one engine in three. The view
    model is where it becomes a whole number to print.
    """
    return snake_ceil(_units_per_box_fraction())


def full_boxes() -> SnakeValue[float]:
    """FRAGMENT: how many boxes go out FULL — the same figure rounded DOWN. NOT executed.

    NOT THE SAME NUMBER AS THE ONE ABOVE, which is the only reason both are here. `ceil` is how many
    labels get printed; `floor` is how many boxes leave sealed, moved by the pallet jack and never
    opened. The gap between them is at most one box and it is the one somebody has to pick by hand,
    which is precisely the line on a picking slip that decides how long the job takes.
    """
    return snake_floor(_units_per_box_fraction())


def _units_per_box_fraction() -> SnakeValue[float]:
    """FRAGMENT: `units / per_box` as a REAL division, which both roundings above stand on.

    Written once because the two questions differ only in which way they round, and two spellings of
    one division is how one of them would quietly stop matching the other.
    """
    return snake_cast(Delivery.units, float) / snake_cast(
        Delivery.packaging.units_per_box, float
    )


def packing_columns() -> tuple[
    SnakeValue[int], SnakeValue[int], SnakeValue[float], SnakeValue[float]
]:
    """FRAGMENT: the four values the picking slip projects, in ONE statement.

    The two roundings travel WITH the numbers they were computed from. Asking for them apart would be
    two passes over one row to answer two halves of one sentence — and worse, it would invite the
    page to recompute in Python what the engine has already said, which is how two figures that must
    agree start disagreeing.
    """
    return (
        Delivery.units,
        Delivery.packaging.units_per_box,
        boxes_needed(),
        full_boxes(),
    )


def packing_slip(
    session: SnakeSession, delivery_id: int
) -> tuple[int, int, int, int] | None:
    """One delivery's packing figures: `(units, per_box, boxes_to_label, full_boxes)`.

    The two roundings arrive as floats — see `boxes_needed` — and leave here as whole numbers, which
    is the one place that conversion belongs: a count of boxes is an integer everywhere except in the
    type the three engines happen to agree on.
    """
    rows = session.select(delivery(delivery_id), *packing_columns())
    if not rows:
        return None
    units, per_box, boxes, full = rows[0]
    return (int(units), int(per_box), int(boxes), int(full))


# --- when must it leave: the dispatch board -------------------------------------------------------


def latest_dispatch() -> SnakeValue[SnakeUtc]:
    """FRAGMENT: the last moment a delivery can leave — the promise, moved BACK by the lead.

    BACKWARDS SCHEDULING, and the direction is the whole point. `billing` shifts a date FORWARD to
    turn an issue date into a due date, which is the only direction a debt ever moves. A delivery
    goes the other way: the customer fixes the END of the chain and the depot works out when the van
    has to be on the road, so the answer is always EARLIER than the fact it is computed from.

    DAYS, and never months. `SnakeDatePart.DAY` is a fixed span that the three engines agree on to
    the second; a calendar month is the unit the ORM declares as `Cap.CALENDAR_INTERVAL` because
    PostgreSQL and MySQL clamp to the end of the month and SQLite overflows past it. A dispatch lead
    is counted in days in every warehouse there has ever been, so this costs nothing at all — but it
    is worth writing down that the portable choice and the natural one are the same choice here.
    """
    return snake_date_sub(Delivery.promised_at, DISPATCH_LEAD_DAYS, SnakeDatePart.DAY)


def dispatch_query(*, limit: int = 20) -> SnakeQuery[Delivery]:
    """FRAGMENT: the deliveries whose promise falls soonest, bounded. NOT executed.

    IT ORDERS BY THE STORED COLUMN and not by the shifted one, which is `billing.overdue_query`'s
    argument holding word for word one domain over: every row's promise moves back by the SAME lead,
    so the two orderings are identical, and only one of them can use an index on `promised_at`. The
    shift is for producing a value somebody READS.
    """
    return (
        SnakeQuery(Delivery)
        .order_by(Delivery.promised_at.asc(), Delivery.id.asc())
        .limit(limit)
    )


def dispatch_columns() -> tuple[
    SnakeValue[int], SnakeValue[str], SnakeValue[SnakeUtc], SnakeValue[SnakeUtc]
]:
    """FRAGMENT: the four values the dispatch board projects, in ONE statement."""
    return (Delivery.id, Delivery.reference, Delivery.promised_at, latest_dispatch())


def dispatch_rows(
    session: SnakeSession, *, limit: int = 20
) -> list[tuple[int, str, str, str]]:
    """The soonest promises, each with the LAST DAY its van can leave, both as calendar days.

    THE NORMALISATION HAPPENS HERE, at the seam where the driver hands the value over, and that is
    the point of this function existing at all. A stored column comes back typed because the row
    mapper knows what it was declared as; a COMPUTED date has no column to know, so PostgreSQL hands
    back a datetime and SQLite ISO-8601 text — it has no date type to type it with, which is the same
    fact `Cap.TIMESTAMPTZ` already declares for stored timestamps.

    Two surfaces read this board — a page and a JSON endpoint — so leaving the shape to whoever
    consumes it would mean the same normalisation written twice, and one of the two written wrong the
    day somebody only tested on SQLite. `billing_viewmodels._day_of` does this one storey up because
    only a page reads its ageing table; here it belongs below both.

    BOTH DATES ARE DAYS, and that is a statement about the domain rather than tidiness: a dispatch
    lead is counted in days in every warehouse there has ever been, so an hour on either end is noise
    that would invite somebody to compare one of them against a timestamp.
    """
    rows = session.select(dispatch_query(limit=limit), *dispatch_columns())
    return [
        (int(id_), reference, day_of(promised), day_of(leave_by))
        for id_, reference, promised, leave_by in rows
    ]


def day_of(value: object) -> str:
    """The calendar day of a value that may arrive as a datetime or as ISO-8601 text.

    Not defensive coding for its own sake: the two shapes are two ENGINES, and the demos run on both
    from the same `.env`. PUBLIC, unlike `billing_viewmodels._day_of`, because the asynchronous twin
    of this domain reads the same computed date and has to normalise it identically — a helper two
    colours share cannot be private to one of them.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10]


# --- how busy is that hour: the load band ---------------------------------------------------------


def band_units() -> SnakeValue[int | None]:
    """FRAGMENT: the units booked in the HOURS around this delivery's slot. NOT executed.

    `RANGE` AND NOT `ROWS`, AND THAT IS THE ENTIRE POINT OF THIS FUNCTION. The two frames look alike
    and answer different questions:

        ROWS BETWEEN 2 PRECEDING AND 2 FOLLOWING     the two bookings either side of this one
        RANGE BETWEEN 2 PRECEDING AND 2 FOLLOWING    everything booked within two HOURS of this one

    A depot's capacity is a property of a TIME BAND, not of a count of neighbouring rows. With `ROWS`,
    three deliveries booked into the same nine o'clock slot get three different windows and three
    different answers to one question — and the third one reaches back to seven o'clock while the
    first stops at eight, because a row is a step regardless of what it is a step of. With `RANGE`
    they are one band and one figure, because ties are not steps: they are the same value.

    `inventory.moving_units` is the mirror image and it argues the other way for the same reason. The
    movement trail counts in MOVEMENTS — two receipts landing in the same second are two facts — so
    `RANGE` there would fold them into one step and quietly widen the window. Same pair of frames,
    opposite calls, decided by what the span is MEASURED IN.

    AND THE BAND REACHES FORWARD. Every other window in these demos looks backwards — how much has
    moved lately, what is owed so far — because history is behind you. A dispatcher's is not: a van
    booked at nine is squeezed by what is waiting at ten exactly as much as by what came in at eight,
    so the frame is CENTRED and the forward half is a bound that reads the future of a row.

    The offsets are counted in the unit `slot_hour` is stored in, which is why that column is an
    integer: a `RANGE` offset is a number on PostgreSQL, MySQL and SQLite alike, and an INTERVAL on
    none of the three.
    """
    return sum_(Delivery.units).over(
        partition_by=(Delivery.depot_id,),
        order_by=(Delivery.slot_hour.asc(),),
        frame=snake_range(snake_preceding(BAND_HOURS), snake_following(BAND_HOURS)),
    )


def slot_load_query(*, limit: int = 40) -> SnakeQuery[Delivery]:
    """FRAGMENT: the bookings, by depot and by hour, bounded. NOT executed.

    The order is the one the band is read in, so the page prints a depot's day top to bottom. It is
    NOT what defines the window — the frame carries its own `ORDER BY` and would compute the same
    figures under any outer order — but a table sorted one way over a window sorted another is a page
    nobody can check by eye.
    """
    return (
        SnakeQuery(Delivery)
        .order_by(
            Delivery.depot_id.asc(), Delivery.slot_hour.asc(), Delivery.reference.asc()
        )
        .limit(limit)
    )


def slot_load_columns() -> tuple[
    SnakeValue[str], SnakeValue[int], SnakeValue[int], SnakeValue[int | None]
]:
    """FRAGMENT: the four values the load page projects, in ONE statement.

    The depot's CODE and not its id, so nothing downstream has to walk `delivery.depot` to print a
    heading — the navigation happens here, where a test can count the statements it costs.
    """
    return (
        Delivery.depot.code,
        Delivery.slot_hour,
        Delivery.units,
        band_units(),
    )


def slot_load_rows(
    session: SnakeSession, *, limit: int = 40
) -> list[tuple[str, int, int, int]]:
    """Each booking with its own units and everything booked within the band around it."""
    rows = session.select(slot_load_query(limit=limit), *slot_load_columns())
    return [
        (code, int(hour), int(units), int(band or 0))
        for code, hour, units, band in rows
    ]
