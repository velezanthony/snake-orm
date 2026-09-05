"""The stock breakdown by status: a `CASE WHEN` the engine groups by, not a bucket filled in Python.

The inventory report already says what every warehouse holds and where each pair ranks. What it never
said is the question a replenishment desk asks first: how many pairs are OUT, how many are LOW, and
how many are fine.

WHY THE CLASSIFICATION HAS TO BE SQL, and this is the whole argument. The three numbers come from a
`GROUP BY`, and you cannot group by a bucket that only exists in Python: doing it here means loading
every stock row — the report's own docstring promises "not one of them depends on the row count" —
and counting them in a loop. A `CASE WHEN` inside the `GROUP BY` gives the engine the classification,
and three rows come back whatever the size of the warehouse.

AND IT USES `available`, NOT `on_hand`. A pair holding fifty units of which forty-five are promised
has five: it is LOW, and a report reading the shelf would have called it healthy. That subtraction is
the same one the `LowStock` view moved to, and it could not be written at all until the ORM learned
to compare a column against a column.

The thresholds are the view's: zero is out, under ten is low. They are written once here and the view
keeps its own copy in the database, which is a duplication worth naming — a view takes no parameters,
so the number has to be inlined there.
"""

from __future__ import annotations

from datetime import date, time, timedelta, timezone
from decimal import Decimal

from snakeorm import SnakeQuery, SnakeSession
from snakeorm.debug import capture_queries

from shared.models import SkuKind
from shared.selectors import inventory_selectors as selectors
from shared.usecases import inventory_usecases as inventory
from shared.usecases.result import Failure


def _warehouse(session: SnakeSession, code: str) -> int:
    """One warehouse through the USE CASE, never a raw insert: the same door a page uses."""
    warehouse = inventory.create_warehouse(
        session,
        code=code,
        name=f"Warehouse {code}",
        opened_on=date(2020, 3, 14),
        shift_start=time(6, 30),
        cutoff=time(18, 0, tzinfo=timezone(timedelta(hours=1))),
    )
    assert not isinstance(warehouse, Failure), warehouse
    return warehouse.id


def _sku(session: SnakeSession, name: str) -> int:
    """One SKU through the use case."""
    sku = inventory.create_sku(
        session,
        name=name,
        kind=SkuKind.PHYSICAL,
        price=Decimal("10.00"),
        weight_kg=1.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(sku, Failure), sku
    return sku.id


def _pair(
    session: SnakeSession, warehouse_id: int, name: str, on_hand: int, reserved: int
) -> None:
    """A pair at the levels the case is about, through the two use cases that own them.

    `count_stock` is the upsert that brings the pair into existence — `update_stock` refuses a pair
    that is not there, and rightly: editing something that does not exist is a different operation.
    """
    sku_id = _sku(session, name)
    counted = inventory.count_stock(
        session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=on_hand
    )
    assert not isinstance(counted, Failure), counted
    updated = inventory.update_stock(
        session,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        on_hand=on_hand,
        reserved=reserved,
    )
    assert not isinstance(updated, Failure), updated


def _seed_three_states(session: SnakeSession) -> int:
    """One pair per status, and the LOW one is low because of what is RESERVED.

    That last one is the case a report over `on_hand` gets wrong: fifty units on the shelf,
    forty-five promised, five available. Reading the shelf calls it healthy.
    """
    warehouse_id = _warehouse(session, "MAD")
    _pair(session, warehouse_id, "OUT", on_hand=0, reserved=0)
    _pair(session, warehouse_id, "LOW", on_hand=50, reserved=45)
    _pair(session, warehouse_id, "OK", on_hand=80, reserved=1)
    session.commit()
    return warehouse_id


def test_it_counts_one_pair_in_each_bucket(session: SnakeSession) -> None:
    """The three statuses, with the counts the seeding put there."""
    _seed_three_states(session)

    breakdown = selectors.stock_by_status(session)

    assert breakdown == [("low", 1), ("ok", 1), ("out", 1)]


def test_low_is_decided_by_what_is_AVAILABLE(session: SnakeSession) -> None:
    """The pair with fifty on the shelf is LOW, because forty-five of them are promised.

    This is the assertion the whole feature exists for. A breakdown over `on_hand` would put that
    pair in `ok`, and every number on the page would still add up.
    """
    _seed_three_states(session)

    breakdown = dict(selectors.stock_by_status(session))

    assert breakdown["low"] == 1
    assert breakdown["ok"] == 1


def test_it_is_ONE_statement_whatever_the_number_of_rows(session: SnakeSession) -> None:
    """One query, and the report's promise is that no figure grows with the data.

    Classifying in Python would mean one statement too — and it would carry every stock row over the
    wire to count three numbers. What is pinned here is that the ENGINE did the grouping, which is
    what the count of returned ROWS shows.
    """
    _seed_three_states(session)
    warehouse_id = _warehouse(session, "BCN")
    for number in range(20):
        _pair(session, warehouse_id, f"X{number}", on_hand=1, reserved=0)
    session.commit()

    with capture_queries() as collector:
        breakdown = selectors.stock_by_status(session)

    report = collector.report()
    assert report.count == 1, report.to_text()
    # Three rows back, not twenty-three: the grouping happened in the engine.
    assert report.records[0].rows == len(breakdown) == 3


def test_an_empty_warehouse_is_an_answer_and_not_a_failure(
    session: SnakeSession,
) -> None:
    """With no stock at all the breakdown is empty, which is a number and not a missing page."""
    assert selectors.stock_by_status(session) == []


def test_the_query_carries_no_rows_of_its_own(session: SnakeSession) -> None:
    """The fragment is a `SnakeQuery` and does not run: the executor above is what runs it.

    Same split as every other selector here — the fragment has no colour, so the asynchronous twin
    consumes the very same object and the two cannot drift into two classifications.
    """
    fragment = selectors.stock_grouped_by_status()

    assert isinstance(fragment, SnakeQuery)
