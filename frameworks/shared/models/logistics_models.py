"""LOGISTICS domain: delivery depots, packaging units and the deliveries that leave from them.

A DEPOT IS NOT A WAREHOUSE, and the two live in different domains on purpose. `inventory.Warehouse`
answers "how much of this is on the shelf"; a depot answers "which van does this go on and when does
it leave". They are the same building often enough for the distinction to be worth stating once: the
questions below are about GEOMETRY and TIME, and none of them can be asked of a stock row.

WHAT THIS DOMAIN IS FOR, in one line each — because a domain that exists to make a tally go up is
the thing this layer's coverage nets are written to refuse:

* **Where does this go?** A delivery carries a destination and every depot carries its own position,
  so "which depot is nearest to this address" is a distance, and a distance is a square root over a
  sum of squares. It is the only question in the demos that has ever needed one.
* **How is it packed?** Units travel in boxes of a fixed size, so the number of boxes to label is
  `units / per_box` rounded UP and the number of FULL boxes is the same figure rounded DOWN. Both
  numbers go on the same picking slip and they are not the same number: the first is how many labels
  get printed, the second is how many boxes the pallet jack moves without anybody opening one.
  NEITHER IS MONEY, which is the whole objection this domain had to clear — the repository's rule is
  that money is formatted from exact integer cents and never rounded in SQL, and it stands untouched.
* **When must it leave?** A delivery is PROMISED for an instant, and the van has to be on the road
  a fixed lead before it. That is backwards scheduling, and it is a date shifted BACKWARD — the half
  of the pair `billing` never had a use for, since a due date only ever moves forward.
* **How busy is that hour?** Deliveries are booked into hourly slots, and the load a depot has to
  absorb around one booking is measured in HOURS, not in a count of neighbouring rows. Two deliveries
  in the same slot are one band, and a band reaches forward as well as back.

THE THREE ENGINES, as everywhere here: no column and no relationship in this file knows which one it
is running on. The coordinates are plain `float`s and the slot is a plain `int`, which is not a
simplification but the condition of the window that reads them — a frame counted in VALUES takes a
numeric offset on PostgreSQL, MySQL and SQLite alike, and an INTERVAL offset on none of the three.
"""

from __future__ import annotations

from snakeorm import (
    SnakeColumn,
    SnakeIndex,
    SnakeModel,
    SnakeToMany,
    SnakeToOne,
    SnakeUtc,
    snake_auto,
    snake_check,
    snake_checks,
    snake_datetimetz,
    snake_float,
    snake_int,
    snake_model,
    snake_str,
    snake_to_many,
    snake_to_one,
)

# How long before the promise the van has to be on the road. A constant of the DOMAIN and not of a
# query: the dispatch board and the delivery sheet answer the same question, and two spellings of
# "two days" is how one page starts telling the reader something the other one denies.
DISPATCH_LEAD_DAYS = 2

# How far either side of a slot the load is measured, in HOURS. It is the half-width of the band, so
# the whole band is twice this plus the slot itself: with 2, a booking at 09:00 is read against
# everything between 07:00 and 11:00.
BAND_HOURS = 2


@snake_model(table="depots")
class Depot(SnakeModel):
    """A dispatch depot: a position on the map and the deliveries that leave from it.

    `code` is FIXED-width for the reason `Warehouse.code` is: it is a three-letter code that goes on
    a label, not a name somebody types.
    """

    SnakeComment = "Dispatch depots that vans leave from"

    id: SnakeColumn[int] = snake_auto()
    code: SnakeColumn[str] = snake_str(max_length=3, fixed=True, unique=True)
    name: SnakeColumn[str] = snake_str(max_length=80)
    # Degrees, and stored as they are read. Nothing here projects onto a sphere: the demos compare
    # distances to pick the SMALLEST, and every monotone transform of a distance orders the same way,
    # so paying for trigonometry would buy a prettier number and not a different answer. Said out
    # loud because a coordinate column invites somebody to assume kilometres.
    latitude: SnakeColumn[float] = snake_float()
    longitude: SnakeColumn[float] = snake_float()
    deliveries: SnakeToMany[Delivery] = snake_to_many("depot")


@snake_model(table="packaging_units")
class PackagingUnit(SnakeModel):
    """How many units go in one box of a given packaging. The divisor of the whole picking slip."""

    SnakeComment = "Packaging kinds and how many units fit in one box"

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(max_length=40, unique=True)
    units_per_box: SnakeColumn[int] = snake_int()
    deliveries: SnakeToMany[Delivery] = snake_to_many("packaging")


@snake_model(table="deliveries")
class Delivery(SnakeModel):
    """One delivery: where it goes, how it is packed, when it is promised and which hour it is booked.

    `depot_id` is the depot it is ASSIGNED to, which is not necessarily the nearest one — that gap is
    the domain's whole reason for computing a distance, and a model that made the two the same by
    construction could not have the question.
    """

    SnakeComment = "Deliveries booked out of a depot"

    id: SnakeColumn[int] = snake_auto()
    reference: SnakeColumn[str] = snake_str(max_length=20, unique=True)
    depot_id: SnakeColumn[int] = snake_int(index=True)
    packaging_id: SnakeColumn[int] = snake_int(index=True)
    depot: SnakeToOne[Depot] = snake_to_one(depot_id)
    packaging: SnakeToOne[PackagingUnit] = snake_to_one(packaging_id)
    units: SnakeColumn[int] = snake_int()
    latitude: SnakeColumn[float] = snake_float()
    longitude: SnakeColumn[float] = snake_float()
    # The hour of the day the van is booked into, 0 to 23. An INTEGER and not a time, and the type is
    # the design rather than a shortcut: the load window below is a frame counted in VALUES, and the
    # only offset the three engines agree on is a number.
    slot_hour: SnakeColumn[int] = snake_int()
    # No server default, and the difference from `Timestamped.created_at` is the point: a creation
    # instant is what the SERVER observed and nobody should be able to type one, while a PROMISE is a
    # commitment somebody made to a customer. It arrives with the row.
    promised_at: SnakeColumn[SnakeUtc] = snake_datetimetz()

    SnakeIndexes = [SnakeIndex(depot_id, slot_hour)]


# Outside the class body, as `inventory` does it: inside it the descriptor does not know its name yet.
#
# THE DIVISOR IS THE ONE THAT MATTERS. `units_per_box` is what the picking slip divides by, and a
# zero there is a division by zero that PostgreSQL refuses outright and SQLite answers with NULL in
# silence — the same split `snake_nullif` was brought in for one domain over. A box that holds
# nothing is not a packaging, so the engine is the place to say so: it is the only layer that still
# holds when two writers race.
snake_checks(
    PackagingUnit,
    snake_check(PackagingUnit.units_per_box > 0, name="ck_packaging_units_per_box"),
)

# A delivery of zero units is not a delivery, and an hour outside the clock is not a slot. The second
# one is what keeps the load band honest: the frame is stated in hours, so a row booked at hour 40
# would sit in a band no van can drive to.
snake_checks(
    Delivery,
    snake_check(Delivery.units > 0, name="ck_deliveries_units_positive"),
    snake_check(Delivery.slot_hour >= 0, name="ck_deliveries_slot_hour_low"),
    snake_check(Delivery.slot_hour <= 23, name="ck_deliveries_slot_hour_high"),
)


# The domain's models, in local dependency order for the DDL.
LOGISTICS_MODELS = (Depot, PackagingUnit, Delivery)
