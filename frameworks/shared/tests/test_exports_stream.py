"""The two CSV exports, and the one thing about them that is worth a test: they STREAM.

An export is the page type the plan added to exercise `session.iterate()`, and `iterate` is the only
read in the ORM whose whole value is invisible in the result. A view model that walked the stream
into a list would return the same rows, in the same order, with the same characters in them, and
every assertion about CONTENT would still pass — while the page had quietly gone back to holding a
million movements in memory before writing the first byte. So the content tests here are the small
half; the big half is the three that measure the SHAPE of the execution.

WHAT PROVES IT, and why each of the three is needed:

- the view model returns a GENERATOR, not a list. That is the type-level half, and on its own it
  proves nothing: `iter(list(...))` is a generator too;
- NOTHING has run when the export is handed back. `iterate` is documented lazy — "nothing is
  executed until the first row is asked for" — so a builder that had materialised would already have
  fired its statement by the time it returned. Zero queries after building is the cheapest possible
  witness and it cannot be faked by a list;
- and the one that closes it: consuming THREE rows out of thirty records THREE. `CaptureDriver`
  notes a streamed statement when the cursor is done rather than when it starts, and what it notes
  is the number of rows CONSUMED. A materialising view model would have consumed all thirty to build
  its list, so the count in the record is the difference between the two implementations, measured
  from outside.

The last one is also why the export is bounded by nothing. A `limit()` would make the first two
tests pass over a query that never had to stream in the first place.
"""

from __future__ import annotations

import inspect
from collections.abc import Generator
from datetime import date, time, timedelta, timezone
from decimal import Decimal

import pytest
from snakeorm import SnakeQuery, SnakeSession
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.debug import capture_queries

from shared.models import (
    MovementReason,
    OrderState,
    SkuKind,
    Stock,
    StockMovement,
    User,
)
from shared.selectors import inventory_selectors, orders_selectors
from shared.usecases import inventory_usecases as inventory
from shared.usecases import orders_usecases as orders
from shared.usecases.result import Failure
from shared.viewmodels import inventory_viewmodels, orders_viewmodels


def _warehouse_and_sku(session: SnakeSession) -> tuple[int, int]:
    """One warehouse and one SKU, built through the use cases rather than with raw inserts."""
    warehouse = inventory.create_warehouse(
        session,
        code="MAD",
        name="Warehouse Madrid",
        opened_on=date(2020, 3, 14),
        shift_start=time(6, 30),
        cutoff=time(18, 0, tzinfo=timezone(timedelta(hours=1))),
    )
    assert not isinstance(warehouse, Failure), warehouse
    sku = inventory.create_sku(
        session,
        name="Widget",
        kind=SkuKind.PHYSICAL,
        price=Decimal("10.00"),
        weight_kg=1.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(sku, Failure), sku
    return warehouse.id, sku.id


def _movements(session: SnakeSession, count: int) -> tuple[int, int]:
    """`count` stock movements on one pair, each one a real `receive`. Returns the pair."""
    warehouse_id, sku_id = _warehouse_and_sku(session)
    for _ in range(count):
        received = inventory.receive(
            session, warehouse_id=warehouse_id, sku_id=sku_id, units=1
        )
        assert not isinstance(received, Failure), received
    return warehouse_id, sku_id


def _order_lines(session: SnakeSession, orders_wanted: int) -> int:
    """`orders_wanted` DRAFT orders of one line each. Returns the warehouse they ship from."""
    warehouse_id, sku_id = _warehouse_and_sku(session)
    counted = inventory.count_stock(
        session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=1000
    )
    assert not isinstance(counted, Failure), counted
    customer = session.add(
        User(username="buyer", email="buyer@demo.dev", password_hash="x")
    )
    session.commit()
    for index in range(orders_wanted):
        placed = orders.place_order(
            session,
            reference=f"ORD-{index:03d}",
            customer_id=customer.id,
            warehouse_id=warehouse_id,
            lines=[(sku_id, 1)],
        )
        assert not isinstance(placed, Failure), placed
    return warehouse_id


def _consume(
    rows: Generator[tuple[str, ...], None, None], how_many: int
) -> list[tuple[str, ...]]:
    """Take `how_many` rows and CLOSE the stream, the way a cancelled download would.

    The close is not tidying: `CaptureDriver` records a streamed statement in a `finally`, so the
    record only lands once the generator chain is torn down. Leaving it to the garbage collector
    would make the assertion depend on when CPython gets round to it.
    """
    taken: list[tuple[str, ...]] = []
    for row in rows:
        taken.append(row)
        if len(taken) == how_many:
            break
    rows.close()
    return taken


# ---- The stock movements export -----------------------------------------------------------------


def test_the_movements_export_hands_back_a_generator_and_not_a_list(
    session: SnakeSession,
) -> None:
    """The type-level half: the rows are a stream, so the web layer can write them as they arrive."""
    _movements(session, 4)

    export = inventory_viewmodels.stock_movements_export(session)

    assert inspect.isgenerator(export.rows), type(export.rows)
    assert not isinstance(export.rows, list)


def test_building_the_movements_export_runs_nothing(session: SnakeSession) -> None:
    """ZERO statements when the export is handed back: `iterate` is lazy and stays lazy here.

    This is what a view model that collected the stream into a list could not do, and it is the
    cheapest witness there is: the statement would already have run.
    """
    _movements(session, 6)

    with capture_queries() as collector:
        export = inventory_viewmodels.stock_movements_export(session)

    assert export.header
    assert collector.report().count == 0, collector.report().to_text()


def test_reading_three_movements_out_of_thirty_reads_three(
    session: SnakeSession,
) -> None:
    """THE test: what the cursor actually consumed, measured from outside the view model.

    `CaptureDriver.fetch_iter` notes the row count when the cursor is done, and in streaming the
    interesting figure IS what was consumed. Thirty rows exist; three are asked for; three is what
    the record says. A view model that had built a list would say thirty, with every content
    assertion in this file still green.
    """
    _movements(session, 30)

    with capture_queries() as collector:
        export = inventory_viewmodels.stock_movements_export(session)
        taken = _consume(export.rows, 3)

    report = collector.report()
    assert len(taken) == 3
    assert report.count == 1, report.to_text()
    assert report.records[0].rows == 3, (
        f"the cursor consumed {report.records[0].rows} rows for a three-row read: the export "
        f"materialised instead of streaming."
    )


def test_the_whole_movements_export_is_one_statement(session: SnakeSession) -> None:
    """ONE, and it stays one at thirty rows: the two to-one hops ride in the same JOIN.

    The literal is the point of this phase's gate. It is one and not three because the warehouse and
    the SKU are `include`d to-one — a to-many `include` would be refused by `iterate` outright, and
    reading the names off each movement instead would be a query per row, in a loop that is by
    definition long.
    """
    _movements(session, 30)

    with capture_queries() as collector:
        export = inventory_viewmodels.stock_movements_export(session)
        rows = list(export.rows)

    assert len(rows) == 30
    assert collector.report().count == 1, collector.report().to_text()


def test_every_movement_cell_is_text_and_matches_the_header(
    session: SnakeSession,
) -> None:
    """A CSV has no types: every cell is already a string, and every row has the header's width."""
    _movements(session, 3)

    export = inventory_viewmodels.stock_movements_export(session)
    rows = list(export.rows)

    assert rows
    for row in rows:
        assert len(row) == len(export.header), f"{row} against {export.header}"
        for cell in row:
            assert isinstance(cell, str), f"not text: {type(cell)} {cell!r}"


def test_the_movement_row_carries_the_names_and_not_only_the_ids(
    session: SnakeSession,
) -> None:
    """The relation navigation happened HERE, which is the whole reason this layer exists.

    A CSV writer that reached for `movement.stock.sku.name` itself would be doing it inside the loop
    that streams, where nothing counts queries and where the loop is a million rows long.
    """
    _movements(session, 2)

    export = inventory_viewmodels.stock_movements_export(session)
    row = dict(zip(export.header, next(export.rows), strict=True))

    assert row["warehouse_code"] == "MAD"
    assert row["sku_name"] == "Widget"
    assert row["reason"] == MovementReason.PURCHASE.value


def test_the_movements_export_narrows_to_one_warehouse(session: SnakeSession) -> None:
    """The filter is the query's, not the writer's: an unwanted row must never leave the database."""
    warehouse_id, _ = _movements(session, 3)

    mine = list(
        inventory_viewmodels.stock_movements_export(
            session, warehouse_id=warehouse_id
        ).rows
    )
    other = list(
        inventory_viewmodels.stock_movements_export(
            session, warehouse_id=warehouse_id + 999
        ).rows
    )

    assert len(mine) == 3
    assert other == []


# ---- The order lines export ----------------------------------------------------------------------


def test_building_the_order_lines_export_runs_nothing(session: SnakeSession) -> None:
    """The second export obeys the same contract, and it is stated once per export on purpose.

    The two are separate code paths over separate tables — one reaches the warehouse through
    `StockMovement.stock`, the other through `OrderLine.order` — and a shared helper is exactly what
    would let one of them be rewritten into a list while the other stayed honest.
    """
    _order_lines(session, 5)

    with capture_queries() as collector:
        export = orders_viewmodels.order_lines_export(session)

    assert export.header
    assert collector.report().count == 0, collector.report().to_text()


def test_reading_three_order_lines_out_of_thirty_reads_three(
    session: SnakeSession,
) -> None:
    """Same measurement on the other big table: what the cursor consumed is what was asked for."""
    _order_lines(session, 30)

    with capture_queries() as collector:
        export = orders_viewmodels.order_lines_export(session)
        taken = _consume(export.rows, 3)

    report = collector.report()
    assert len(taken) == 3
    assert report.count == 1, report.to_text()
    assert report.records[0].rows == 3, (
        f"the cursor consumed {report.records[0].rows} rows for a three-row read: the export "
        f"materialised instead of streaming."
    )


def test_the_whole_order_lines_export_is_one_statement(session: SnakeSession) -> None:
    """ONE, at thirty lines, with THREE to-one hops in it: order, customer, warehouse and SKU.

    The customer and the warehouse are reached THROUGH the order, which is a two-step to-one path,
    and it still costs nothing extra: they are all LEFT JOINs on the same SELECT. That is the whole
    reason an export can afford to print names at all.
    """
    _order_lines(session, 30)

    with capture_queries() as collector:
        export = orders_viewmodels.order_lines_export(session)
        rows = list(export.rows)

    assert len(rows) == 30
    assert collector.report().count == 1, collector.report().to_text()


def test_every_order_line_cell_is_text_and_matches_the_header(
    session: SnakeSession,
) -> None:
    """Same CSV contract: text only, and as wide as the header says."""
    _order_lines(session, 3)

    export = orders_viewmodels.order_lines_export(session)
    rows = list(export.rows)

    assert rows
    for row in rows:
        assert len(row) == len(export.header), f"{row} against {export.header}"
        for cell in row:
            assert isinstance(cell, str), f"not text: {type(cell)} {cell!r}"


def test_the_line_total_is_computed_here_and_not_left_to_a_spreadsheet(
    session: SnakeSession,
) -> None:
    """`quantity * unit_price` is one multiplication, and a spreadsheet formula is not an export.

    It is the same argument `available` makes on the stock listing: an arithmetic left to whoever
    reads the file is an arithmetic that gets done two ways.
    """
    _order_lines(session, 1)

    export = orders_viewmodels.order_lines_export(session)
    row = dict(zip(export.header, next(export.rows), strict=True))

    assert row["quantity"] == "1"
    assert row["unit_price"] == "10.00"
    assert row["line_total"] == "10.00"
    assert row["customer"] == "buyer"
    assert row["warehouse_code"] == "MAD"


def test_the_order_lines_export_narrows_to_one_state(session: SnakeSession) -> None:
    """The state filter travels into the WHERE, so a settled order never leaves the database."""
    _order_lines(session, 4)

    drafts = list(orders_viewmodels.order_lines_export(session).rows)
    settled = list(
        orders_viewmodels.order_lines_export(session, state=OrderState.SETTLED).rows
    )

    assert len(drafts) == 4
    assert settled == []


# ---- What streaming refuses, and why the export is built the way it is ----------------------------


def test_streaming_refuses_a_to_many_include(session: SnakeSession) -> None:
    """Half of the rule the exports are SHAPED by, pinned so the shape has a reason on file.

    `iterate` refuses a to-many `include` because the select-in needs every root to fire its second
    query, and in streaming the roots do not exist yet — serving it would mean materialising (which
    is what the export exists to avoid) or one query per row. It raises on the CALL and not on the
    first `next()`, which is why this is a one-liner and not a loop.
    """
    with pytest.raises(SnakeUnsupportedFeature):
        session.iterate(SnakeQuery(Stock).include(Stock.movements))


def test_streaming_accepts_a_to_one_include(session: SnakeSession) -> None:
    """The other half, and the reason both exports are built entirely out of to-one hops.

    A to-one `include` rides in the same JOIN, so it costs the export nothing and buys it every name
    it prints. Without it the CSV would carry ids, or the writer would navigate relations inside the
    streaming loop — a query per row, in a loop that is by definition long.
    """
    assert (
        list(session.iterate(SnakeQuery(StockMovement).include(StockMovement.stock)))
        == []
    )


def test_the_export_queries_are_streamable_by_construction() -> None:
    """Neither export query carries a to-many include or a prefetch, checked on the query itself.

    Asking the query rather than running it is what makes this a statement about the SHAPE: an
    export that grew a to-many `include` would fail here at build time instead of at the first
    download of a file somebody was waiting for.
    """
    for built in (
        inventory_selectors.movements_to_export(),
        orders_selectors.lines_to_export(),
    ):
        assert built.to_many_includes() == (), built
        assert built.prefetches() == (), built
        assert built.to_one_includes() != (), (
            f"{built} includes nothing: the export would print ids instead of names, or navigate "
            f"relations inside the streaming loop."
        )
