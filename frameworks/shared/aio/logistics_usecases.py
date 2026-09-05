"""logistics domain (depots, delivery sheets, dispatch boards and slot load), asked of an `AsyncSession`.

The twin of `shared/usecases/logistics_usecases.py`: same names, same parameters, same answers. Every
statement comes from `shared/selectors/logistics_selectors.py` untouched, and every SHAPE — the sheet,
the packing slip, the ranking, the bands — is built by the colourless helpers of the synchronous
module rather than assembled again here.

That second half is what this domain needed most. A `SnakeQuery` and a projected column are values,
so the square root behind the depot ranking, the two roundings on the picking slip, the backwards date
shift and the `RANGE` frame cannot drift into two spellings of one question. But this domain's answers
carry DECISIONS as well as figures — is the assigned depot the nearest one, how many units are loose,
which band is the peak — and a decision written twice is the failure the whole `shared/` layer exists
to stop. `_sheet` and `_bands` run no statement, so both colours call the same two functions.

What is left over here is the awaiting, which is the only thing `await` being syntax actually forces.
"""

from __future__ import annotations

from snakeorm import AsyncSession

from shared.models import Delivery, Depot
from shared.selectors.logistics_selectors import (
    NEAREST_DEPOTS,
    delivery,
    depot_columns,
    depots,
    depots_by_distance,
    dispatch_columns,
    dispatch_query,
    distance_to,
    packing_columns,
    slot_load_columns,
    slot_load_query,
)
from shared.selectors.logistics_selectors import day_of

# `_sheet` and `_bands` keep their underscore ON PURPOSE, and it is load-bearing rather than a
# habit: `test_async_mirror.py` demands an asynchronous twin for every PUBLIC function of the
# synchronous module, so naming either of them without one would have this file owe a twin of a
# helper that runs no statement and has no colour to have.
from shared.usecases.logistics_usecases import (
    DeliverySheet,
    DepotSummary,
    DispatchEntry,
    SlotBand,
    _bands,
    _sheet,
)
from shared.usecases.result import Failure


async def list_depots(session: AsyncSession) -> list[DepotSummary]:
    """Every depot with how many deliveries it carries and the units those come to."""
    rows = await session.select(depots(), *depot_columns())
    return [
        DepotSummary(code=code, name=name, deliveries=int(deliveries), units=int(units))
        for code, name, deliveries, units in rows
    ]


async def delivery_sheet(
    session: AsyncSession, delivery_id: int
) -> DeliverySheet | Failure:
    """One delivery, the depots nearest to it, and its packing figures. `not_found` if there is none."""
    found = await _find(session, delivery_id)
    if found is None:
        return Failure("not_found")
    packing = await session.select(delivery(delivery_id), *packing_columns())
    if not packing:
        return Failure("not_found")
    units, per_box, boxes, full = packing[0]
    ranking = await _nearest(
        session, found.latitude, found.longitude, limit=NEAREST_DEPOTS
    )
    return _sheet(found, ranking, (int(units), int(per_box), int(boxes), int(full)))


async def dispatch_board(
    session: AsyncSession, *, limit: int = 20
) -> list[DispatchEntry]:
    """The soonest promises, each with the last day its van can leave to keep them.

    `day_of` is the synchronous selector's own normaliser, imported rather than copied: a computed
    date is typed on PostgreSQL and ISO-8601 text on SQLite, and two colours disagreeing about which
    of the two shapes to expect is exactly the drift `test_sync_async_parity.py` was built after.
    """
    rows = await session.select(dispatch_query(limit=limit), *dispatch_columns())
    return [
        DispatchEntry(
            delivery_id=int(delivery_id),
            reference=reference,
            promised_on=day_of(promised),
            leave_by=day_of(leave_by),
        )
        for delivery_id, reference, promised, leave_by in rows
    ]


async def slot_load(session: AsyncSession, *, limit: int = 40) -> list[SlotBand]:
    """Each booking with everything booked within the same hours of the same depot."""
    rows = await session.select(slot_load_query(limit=limit), *slot_load_columns())
    return _bands(
        [
            (code, int(hour), int(units), int(band or 0))
            for code, hour, units, band in rows
        ]
    )


async def reroute_delivery(
    session: AsyncSession, delivery_id: int
) -> DeliverySheet | Failure:
    """Moves a delivery to the depot nearest its destination. `not_found` if there is no such one.

    Idempotent, like its synchronous twin, and it re-reads the sheet for the same reason: the row
    loaded above carries the depot it was joined with, so after the field changes that object names
    the depot it has just stopped being routed to.
    """
    found = await _find(session, delivery_id)
    if found is None:
        return Failure("not_found")
    ranking = await _nearest(session, found.latitude, found.longitude, limit=1)
    if not ranking:
        return Failure("not_found")
    found.depot_id = ranking[0][0]
    await session.update(found)
    await session.commit()
    return await delivery_sheet(session, delivery_id)


async def _find(session: AsyncSession, delivery_id: int) -> Delivery | None:
    """One delivery by id. Private, and the two operations above go through it TOGETHER.

    The synchronous twin reads it through `selectors.find_delivery`, so its two reads share one call
    site and the panel groups them as a repeat. Two inline `session.first` here would be two sites
    that each ran once — the same work, invisible — and the colours would disagree about what the
    ORM says.
    """
    return await session.first(delivery(delivery_id))


async def _nearest(
    session: AsyncSession, latitude: float, longitude: float, *, limit: int
) -> list[tuple[int, str, str, float]]:
    """The nearest depots to a point. Private: a step of the two operations above, not one of them."""
    rows = await session.select(
        depots_by_distance(latitude, longitude, limit=limit),
        Depot.id,
        Depot.code,
        Depot.name,
        distance_to(latitude, longitude),
    )
    return [(int(id_), code, name, float(far)) for id_, code, name, far in rows]
