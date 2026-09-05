"""The logistics domain: a distance, two roundings, a date shifted backward and a window by VALUE.

Four questions and seven declarators, and this file exists because in every one of the four the WRONG
answer is a plausible one. That is the thread through it: none of these failures announces itself.

    the distance      a ranking is right or wrong by one place, and both look like a list of depots
    the two roundings integer division answers `0` on two engines of three, and `CEIL(0)` is `0` —
                      a picking slip saying a delivery needs no boxes at all, in a table of numbers
    the shift         a date two days early and a date two days late are the same shape
    the window        `RANGE` and `ROWS` differ only when rows TIE, and a seed without a tie draws
                      the same table either way

So the assertions come in pairs wherever a pair is what separates the answer from its lookalike: the
figure AND the statement that produced it, the tie AND the two rows that share a band, the sheet
BEFORE the reroute and after. A test that only read the numbers back would pass over `ROWS`.

The fixtures build their own rows through the models rather than leaning on the seeder, and that is
deliberate for this domain above the others: three of the four questions are about ARITHMETIC, and
arithmetic needs numbers somebody chose. `35 / 12` is on this page because it does not divide, and a
seeded delivery that happened to divide evenly would take the ceiling and the floor apart from each
other without anybody noticing.
"""

from __future__ import annotations

from snakeorm import SnakeSession, SnakeUtc
from snakeorm.debug import capture_queries

from shared.models import Delivery, Depot, PackagingUnit
from shared.usecases import logistics_usecases as usecases
from shared.usecases.result import Failure
from shared.viewmodels import logistics_viewmodels as viewmodels

# A promise far enough from either end of a month that subtracting the lead cannot cross one. The
# shift is counted in DAYS, which the three engines spell identically — but a test that straddled a
# month boundary would be asserting the calendar as well as the shift, and only one of the two is
# under test here.
_PROMISED = SnakeUtc(2026, 6, 15, 9, 0)


def _depot(session: SnakeSession, code: str, latitude: float, longitude: float) -> int:
    """One depot at a chosen point. The coordinates are the whole fixture, so they are arguments."""
    depot = session.add(
        Depot(code=code, name=f"Depot {code}", latitude=latitude, longitude=longitude)
    )
    session.commit()
    return depot.id


def _packaging(session: SnakeSession, name: str, units_per_box: int) -> int:
    """One box size. It is the DIVISOR of the picking slip, which is why every test picks its own."""
    packaging = session.add(PackagingUnit(name=name, units_per_box=units_per_box))
    session.commit()
    return packaging.id


def _delivery(
    session: SnakeSession,
    *,
    reference: str,
    depot_id: int,
    packaging_id: int,
    units: int,
    latitude: float,
    longitude: float,
    slot_hour: int,
    promised_at: SnakeUtc = _PROMISED,
) -> int:
    """One delivery, with every number that matters written out at the call site.

    Keyword-only on purpose: this row carries two coordinates, an hour and a count, and four bare
    numbers in a row is how a fixture ends up asserting something other than what it says.
    """
    delivery = session.add(
        Delivery(
            reference=reference,
            depot_id=depot_id,
            packaging_id=packaging_id,
            units=units,
            latitude=latitude,
            longitude=longitude,
            slot_hour=slot_hour,
            promised_at=promised_at,
        )
    )
    session.commit()
    return delivery.id


def _three_depots(session: SnakeSession) -> tuple[int, int, int]:
    """Three depots on one line, a whole degree apart, so the ranking from any point is unambiguous."""
    return (
        _depot(session, "AAA", 40.0, 0.0),
        _depot(session, "BBB", 41.0, 0.0),
        _depot(session, "CCC", 43.0, 0.0),
    )


# ---- the distance: SQRT over POWERs ---------------------------------------------------------------


def test_the_depots_come_back_nearest_first(session: SnakeSession) -> None:
    """The ranking is by distance to the delivery's destination, closest first.

    The destination sits at 41.2, so the order has to be BBB (0.2), AAA (1.2), CCC (1.8) — which is
    NOT the order the rows were inserted in and not the order of their codes either. Both of those
    would pass a weaker assertion, and both are what a ranking looks like when the ORDER BY key
    silently stopped being the distance.
    """
    near, middle, far = _three_depots(session)
    packaging = _packaging(session, "carton", 12)
    delivery = _delivery(
        session,
        reference="DLV-1",
        depot_id=far,
        packaging_id=packaging,
        units=35,
        latitude=41.2,
        longitude=0.0,
        slot_hour=9,
    )

    sheet = usecases.delivery_sheet(session, delivery)

    assert not isinstance(sheet, Failure), sheet
    assert [row.code for row in sheet.nearest] == ["BBB", "AAA", "CCC"]
    assert sheet.nearest[0].depot_id == middle
    assert near in {row.depot_id for row in sheet.nearest}


def test_the_ranking_is_a_square_root_the_engine_computes(
    session: SnakeSession,
) -> None:
    """And it is computed in SQL, not by sorting depots in Python after fetching them all.

    The two produce the same list at three depots and stop being comparable at three thousand: one
    orders where the rows are and carries three of them back, the other carries every depot over the
    wire to discard all but three. Reading the emitted statement is the only way to tell which is
    happening, because the answer is identical.
    """
    _three_depots(session)
    packaging = _packaging(session, "carton", 12)
    delivery = _delivery(
        session,
        reference="DLV-1",
        depot_id=1,
        packaging_id=packaging,
        units=35,
        latitude=41.2,
        longitude=0.0,
        slot_hour=9,
    )

    with capture_queries() as collector:
        usecases.delivery_sheet(session, delivery)

    emitted = collector.report()
    ranking = [record for record in emitted.records if "SQRT" in record.sql.upper()]
    assert ranking, emitted.to_text()
    assert "POWER" in ranking[0].sql.upper(), emitted.to_text()
    assert "ORDER BY" in ranking[0].sql.upper(), emitted.to_text()


def test_the_point_travels_as_parameters_and_not_in_the_statement(
    session: SnakeSession,
) -> None:
    """The delivery's coordinates are DATA, so they bind rather than reaching the SQL string.

    It is the rule the whole ORM is built on and it is worth pinning here specifically: a distance is
    a formula, and a formula is the one shape that invites somebody to build it with an f-string.
    """
    _three_depots(session)
    packaging = _packaging(session, "carton", 12)
    delivery = _delivery(
        session,
        reference="DLV-1",
        depot_id=1,
        packaging_id=packaging,
        units=35,
        latitude=41.25,
        longitude=0.5,
        slot_hour=9,
    )

    with capture_queries() as collector:
        usecases.delivery_sheet(session, delivery)

    emitted = collector.report()
    ranking = [record for record in emitted.records if "SQRT" in record.sql.upper()]
    assert ranking, emitted.to_text()
    assert "41.25" not in ranking[0].sql, emitted.to_text()
    assert 41.25 in ranking[0].params, emitted.to_text()


# ---- the packing slip: CEIL and FLOOR -------------------------------------------------------------


def test_the_slip_rounds_up_for_the_labels_and_down_for_the_sealed_boxes(
    session: SnakeSession,
) -> None:
    """Thirty-five units in boxes of twelve are THREE boxes to label and TWO that leave sealed.

    The two numbers are the reason both roundings are here, and the eleven loose units between them
    are the reason a picker cares which is which. A slip that printed one figure would leave somebody
    doing this division by hand on a warehouse floor.
    """
    depot = _depot(session, "AAA", 40.0, 0.0)
    packaging = _packaging(session, "carton", 12)
    delivery = _delivery(
        session,
        reference="DLV-1",
        depot_id=depot,
        packaging_id=packaging,
        units=35,
        latitude=40.0,
        longitude=0.0,
        slot_hour=9,
    )

    sheet = usecases.delivery_sheet(session, delivery)

    assert not isinstance(sheet, Failure), sheet
    assert sheet.packing.boxes == 3
    assert sheet.packing.full_boxes == 2
    assert sheet.packing.loose_units == 11


def test_an_exact_load_makes_the_two_roundings_agree(session: SnakeSession) -> None:
    """Thirty-six units in boxes of twelve are three boxes either way, and nothing is left loose.

    The companion of the test above, and it is not symmetry for its own sake: the two roundings are
    EQUAL whenever the division comes out exact, so a suite that only ever asked about an exact load
    would pass with `floor` written where `ceil` belongs. This pins the case where they agree so the
    other one means something.
    """
    depot = _depot(session, "AAA", 40.0, 0.0)
    packaging = _packaging(session, "carton", 12)
    delivery = _delivery(
        session,
        reference="DLV-1",
        depot_id=depot,
        packaging_id=packaging,
        units=36,
        latitude=40.0,
        longitude=0.0,
        slot_hour=9,
    )

    sheet = usecases.delivery_sheet(session, delivery)

    assert not isinstance(sheet, Failure), sheet
    assert sheet.packing.boxes == 3
    assert sheet.packing.full_boxes == 3
    assert sheet.packing.loose_units == 0


def test_a_load_smaller_than_one_box_still_needs_a_box(session: SnakeSession) -> None:
    """One unit in boxes of twelve is ONE box to label and ZERO that leave sealed.

    This is the case integer division gets catastrophically wrong rather than slightly: `1 / 12` is
    `0` on PostgreSQL and SQLite, `CEIL(0)` is `0`, and the slip would say the delivery needs no
    boxes at all. The cast in `_units_per_box_fraction` is what stands between this page and that
    number, and this is the row that would notice if it were removed.
    """
    depot = _depot(session, "AAA", 40.0, 0.0)
    packaging = _packaging(session, "carton", 12)
    delivery = _delivery(
        session,
        reference="DLV-1",
        depot_id=depot,
        packaging_id=packaging,
        units=1,
        latitude=40.0,
        longitude=0.0,
        slot_hour=9,
    )

    sheet = usecases.delivery_sheet(session, delivery)

    assert not isinstance(sheet, Failure), sheet
    assert sheet.packing.boxes == 1
    assert sheet.packing.full_boxes == 0
    assert sheet.packing.loose_units == 1


# ---- the dispatch deadline: a date shifted BACKWARD -----------------------------------------------


def test_the_van_has_to_leave_before_the_promise(session: SnakeSession) -> None:
    """The deadline is the promise minus the lead, so it is EARLIER — the direction billing lacks.

    Asserted as a literal day rather than as "two days less than whatever came back", because the
    second form is the arithmetic under test written twice: it would pass with the sign flipped as
    long as both halves flipped together.
    """
    depot = _depot(session, "AAA", 40.0, 0.0)
    packaging = _packaging(session, "carton", 12)
    _delivery(
        session,
        reference="DLV-1",
        depot_id=depot,
        packaging_id=packaging,
        units=35,
        latitude=40.0,
        longitude=0.0,
        slot_hour=9,
    )

    board = usecases.dispatch_board(session)

    assert [entry.promised_on for entry in board] == ["2026-06-15"]
    assert [entry.leave_by for entry in board] == ["2026-06-13"]


def test_the_board_orders_by_the_stored_promise(session: SnakeSession) -> None:
    """And it orders by the COLUMN, not by the shifted value, which is what lets an index serve it.

    The two orderings agree — every row moves back by the same lead — so no assertion on the ANSWER
    can tell them apart. The statement can: a shifted expression in the `ORDER BY` has to be computed
    for every row before anything can be discarded.
    """
    depot = _depot(session, "AAA", 40.0, 0.0)
    packaging = _packaging(session, "carton", 12)
    _delivery(
        session,
        reference="DLV-2",
        depot_id=depot,
        packaging_id=packaging,
        units=35,
        latitude=40.0,
        longitude=0.0,
        slot_hour=9,
        promised_at=SnakeUtc(2026, 6, 20, 9, 0),
    )
    _delivery(
        session,
        reference="DLV-1",
        depot_id=depot,
        packaging_id=packaging,
        units=35,
        latitude=40.0,
        longitude=0.0,
        slot_hour=9,
    )

    with capture_queries() as collector:
        board = usecases.dispatch_board(session)

    emitted = collector.report()
    assert [entry.reference for entry in board] == ["DLV-1", "DLV-2"]
    order_by = emitted.records[0].sql.upper().split("ORDER BY")[1]
    assert "PROMISED_AT" in order_by, emitted.to_text()


# ---- the load band: RANGE and not ROWS ------------------------------------------------------------


def _one_depot_with_a_tie(session: SnakeSession) -> int:
    """One depot with three bookings, TWO of them in the same hour. The tie is the whole fixture.

    Hours 8, 8 and 9 with 10, 20 and 30 units. Every one of the three is inside a band of two hours
    of every other, so with `RANGE` all three read 60 — and with `ROWS` the first would see only two
    of them. The tie is what makes the two frames disagree; without it this fixture proves nothing.
    """
    depot = _depot(session, "AAA", 40.0, 0.0)
    packaging = _packaging(session, "carton", 12)
    for reference, units, hour in (
        ("DLV-1", 10, 8),
        ("DLV-2", 20, 8),
        ("DLV-3", 30, 9),
    ):
        _delivery(
            session,
            reference=reference,
            depot_id=depot,
            packaging_id=packaging,
            units=units,
            latitude=40.0,
            longitude=0.0,
            slot_hour=hour,
        )
    return depot


def test_two_bookings_in_the_same_hour_read_the_same_band(
    session: SnakeSession,
) -> None:
    """A band is a property of the HOUR, so tied rows share one figure instead of getting three.

    This is the assertion `ROWS` fails. With a frame counted in rows, the two bookings at eight
    o'clock are two steps apart from each other and each gets a window of its own — three different
    answers to one question about one depot's morning.
    """
    _one_depot_with_a_tie(session)

    bands = usecases.slot_load(session)

    assert [band.slot_hour for band in bands] == [8, 8, 9]
    assert [band.band_units for band in bands] == [60, 60, 60]


def test_the_band_is_asked_for_as_a_range(session: SnakeSession) -> None:
    """And the frame emitted is `RANGE`, reaching FORWARD as well as back.

    The figures above would also come out of a wide enough `ROWS` frame on this particular fixture,
    which is exactly why the statement is read as well: what is under test is the frame, and a window
    is the one construct whose meaning changes entirely without the answer changing at all.
    """
    _one_depot_with_a_tie(session)

    with capture_queries() as collector:
        usecases.slot_load(session)

    emitted = collector.report()
    sql = emitted.records[0].sql.upper()
    assert "RANGE BETWEEN" in sql, emitted.to_text()
    assert "FOLLOWING" in sql, emitted.to_text()
    assert "ROWS BETWEEN" not in sql, emitted.to_text()


def test_the_band_stops_at_the_edge_of_the_depot(session: SnakeSession) -> None:
    """A band never reaches into another depot's day: the window is PARTITIONED by depot.

    Two depots booked at the same hour are two vans in two towns, and adding their loads together
    would answer a question nobody asked. Without the partition the figures here would be 40 and 40
    instead of 10 and 30.
    """
    first = _depot(session, "AAA", 40.0, 0.0)
    second = _depot(session, "BBB", 41.0, 0.0)
    packaging = _packaging(session, "carton", 12)
    for reference, depot_id, units in (("DLV-1", first, 10), ("DLV-2", second, 30)):
        _delivery(
            session,
            reference=reference,
            depot_id=depot_id,
            packaging_id=packaging,
            units=units,
            latitude=40.0,
            longitude=0.0,
            slot_hour=9,
        )

    bands = usecases.slot_load(session)

    assert {(band.depot, band.band_units) for band in bands} == {
        ("AAA", 10),
        ("BBB", 30),
    }


def test_the_busiest_band_is_marked_once_the_rows_have_arrived(
    session: SnakeSession,
) -> None:
    """`is_peak` is a property of the PAGE, so it is decided over rows rather than by a second query.

    The peak is "the busiest band among the ones being shown", which is a question about this
    result — asking the engine would be a second statement about the first one's output.
    """
    first = _depot(session, "AAA", 40.0, 0.0)
    second = _depot(session, "BBB", 41.0, 0.0)
    packaging = _packaging(session, "carton", 12)
    for reference, depot_id, units in (("DLV-1", first, 10), ("DLV-2", second, 30)):
        _delivery(
            session,
            reference=reference,
            depot_id=depot_id,
            packaging_id=packaging,
            units=units,
            latitude=40.0,
            longitude=0.0,
            slot_hour=9,
        )

    with capture_queries() as collector:
        bands = usecases.slot_load(session)

    assert collector.report().count == 1, collector.report().to_text()
    assert [band.is_peak for band in bands] == [False, True]


# ---- the reroute: the domain's one write ----------------------------------------------------------


def test_the_sheet_says_when_a_delivery_is_not_leaving_from_the_nearest_depot(
    session: SnakeSession,
) -> None:
    """The verdict is on the sheet, so nobody has to compare a code against the first row by eye."""
    near, _, far = _three_depots(session)
    packaging = _packaging(session, "carton", 12)
    delivery = _delivery(
        session,
        reference="DLV-1",
        depot_id=far,
        packaging_id=packaging,
        units=35,
        latitude=40.0,
        longitude=0.0,
        slot_hour=9,
    )

    sheet = usecases.delivery_sheet(session, delivery)

    assert not isinstance(sheet, Failure), sheet
    assert sheet.depot == "CCC"
    assert sheet.is_routed_to_the_nearest is False
    assert sheet.nearest[0].depot_id == near


def test_rerouting_moves_the_delivery_and_the_sheet_says_so(
    session: SnakeSession,
) -> None:
    """The write picks the nearest depot and answers with the sheet as it NOW reads.

    Both halves matter. A reroute that wrote the right depot and answered with a stale sheet would
    show the old code on the page it just changed — which is the trap of an ORM with no identity map:
    the row in hand carries the depot it was JOINED with, not the one the field now names.
    """
    near, _, far = _three_depots(session)
    packaging = _packaging(session, "carton", 12)
    delivery = _delivery(
        session,
        reference="DLV-1",
        depot_id=far,
        packaging_id=packaging,
        units=35,
        latitude=40.0,
        longitude=0.0,
        slot_hour=9,
    )

    sheet = usecases.reroute_delivery(session, delivery)

    assert not isinstance(sheet, Failure), sheet
    assert sheet.depot == "AAA"
    assert sheet.is_routed_to_the_nearest is True
    assert usecases.delivery_sheet(session, delivery) == sheet
    assert near == sheet.nearest[0].depot_id


def test_rerouting_twice_is_rerouting_once(session: SnakeSession) -> None:
    """It is a button, and a button gets pressed twice: the second press changes nothing and says so.

    The alternative — refusing once the delivery is already on its nearest depot — would tell
    somebody who did exactly the right thing that they failed. It is the same call `tag_post` made
    for the same reason, one domain over.
    """
    _, _, far = _three_depots(session)
    packaging = _packaging(session, "carton", 12)
    delivery = _delivery(
        session,
        reference="DLV-1",
        depot_id=far,
        packaging_id=packaging,
        units=35,
        latitude=40.0,
        longitude=0.0,
        slot_hour=9,
    )

    first = usecases.reroute_delivery(session, delivery)
    second = usecases.reroute_delivery(session, delivery)

    assert first == second


def test_a_delivery_that_is_not_there_is_a_refusal_and_not_an_empty_sheet(
    session: SnakeSession,
) -> None:
    """Both operations refuse by name, so a page can 404 instead of drawing a sheet about nothing."""
    _three_depots(session)

    assert usecases.delivery_sheet(session, 9999) == Failure("not_found")
    assert usecases.reroute_delivery(session, 9999) == Failure("not_found")


# ---- the depot listing: one statement whatever the number of depots -------------------------------


def test_the_depot_listing_costs_one_statement(session: SnakeSession) -> None:
    """Both figures per depot are correlated aggregates, so the page does not grow a query per row.

    Walking `depot.deliveries` from a template would paint the same table at one query per depot —
    an N+1 inside the renderer, which is the layer no `assert_queries` in the demos watches.
    """
    _one_depot_with_a_tie(session)
    _depot(session, "ZZZ", 44.0, 0.0)

    with capture_queries() as collector:
        page = viewmodels.depot_list(session)

    assert collector.report().count == 1, collector.report().to_text()
    assert page["depot_count"] == 2
    assert page["total_units"] == 60


def test_a_depot_with_nothing_booked_holds_zero_and_not_none(
    session: SnakeSession,
) -> None:
    """`SUM` over no rows is NULL on every engine, and a depot with no deliveries holds ZERO units.

    The `COALESCE` is inside the statement rather than in Python, which is what keeps the column
    non-nullable all the way to the page — otherwise the template would have to print the word
    "None" or grow an `if` about it.
    """
    _depot(session, "AAA", 40.0, 0.0)

    page = viewmodels.depot_list(session)

    assert page["depots"] == [
        {"code": "AAA", "name": "Depot AAA", "deliveries": 0, "units": 0}
    ]


# ---- what the pages print -------------------------------------------------------------------------


def test_the_pages_emit_primitives_a_template_can_print(session: SnakeSession) -> None:
    """Nothing that reaches a template is a model, a Decimal or a date object.

    The rule the whole view-model layer keeps, and it bites hardest here: three of this domain's four
    screens print something the ENGINE computed, and a computed date arrives typed on PostgreSQL and
    as text on SQLite. A template deciding how to render that would be two templates deciding it
    differently.
    """
    _one_depot_with_a_tie(session)

    dispatch = viewmodels.dispatch_board(session)
    load = viewmodels.slot_load(session)
    sheet = viewmodels.delivery_sheet(session, 1)

    assert not isinstance(sheet, Failure), sheet
    assert all(isinstance(row["leave_by"], str) for row in dispatch["rows"])
    assert all(isinstance(row["slot"], str) for row in load["rows"])
    assert sheet["slot"] == "08:00"
    assert all(isinstance(row["distance"], str) for row in sheet["nearest"])
