"""How much of each pair is already promised — and the pair holding nothing divides by zero.

`reserved / on_hand` is the ordinary question a replenishment desk asks: fifty on the shelf with
forty-five promised is ninety per cent committed. A pair holding NOTHING is a normal state — it is
one of the three the status breakdown counts — and it makes that division a division by zero.

WHAT THE ENGINES DO, measured rather than assumed:

    SQLite      SELECT 10/0   ->  NULL, silently
    PostgreSQL  SELECT 10/0   ->  DivisionByZero: division by zero

So the same code, over the same rows, answers differently depending on the `.env`: on one engine the
report shows a blank cell and on the other the page is a 500. That is the worst shape a difference
can take, because the demo that gets tested is whichever one the developer happens to be running.

`NULLIF(on_hand, 0)` turns the divisor into NULL before the division happens, and NULL divided into
is NULL on every engine. The blank cell becomes the ANSWER — "nothing on the shelf, so no fraction of
it is promised" — instead of one engine's accident.

WHY NOT `WHERE on_hand > 0`. Because the empty pairs are the ones the desk needs to see. Filtering
them out answers the question by removing the rows that make it interesting.
"""

from __future__ import annotations

from datetime import date, time, timedelta, timezone
from decimal import Decimal

import pytest
from snakeorm import SnakeSession
from snakeorm.drivers import SnakeDriver

from shared.models import SkuKind
from shared.selectors import inventory_selectors as selectors
from shared.usecases import inventory_usecases as inventory
from shared.usecases.result import Failure


def _warehouse(session: SnakeSession, code: str) -> int:
    """One warehouse through the use case, the same door a page uses."""
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


def _pair(
    session: SnakeSession, warehouse_id: int, name: str, on_hand: int, reserved: int
) -> None:
    """A pair at those levels: `count_stock` brings it into being, `update_stock` sets what is held."""
    sku = inventory.create_sku(
        session,
        name=name,
        kind=SkuKind.PHYSICAL,
        price=Decimal("10.00"),
        weight_kg=1.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(sku, Failure), sku
    counted = inventory.count_stock(
        session, warehouse_id=warehouse_id, sku_id=sku.id, on_hand=on_hand
    )
    assert not isinstance(counted, Failure), counted
    updated = inventory.update_stock(
        session,
        warehouse_id=warehouse_id,
        sku_id=sku.id,
        on_hand=on_hand,
        reserved=reserved,
    )
    assert not isinstance(updated, Failure), updated


def _seed(session: SnakeSession) -> None:
    """Three pairs: one mostly promised, one untouched, and one holding nothing at all."""
    warehouse_id = _warehouse(session, "MAD")
    _pair(session, warehouse_id, "Committed", on_hand=50, reserved=45)
    _pair(session, warehouse_id, "Free", on_hand=80, reserved=0)
    _pair(session, warehouse_id, "Empty", on_hand=0, reserved=0)
    session.commit()


def test_the_empty_pair_does_not_blow_up_the_report(session: SnakeSession) -> None:
    """The whole point: the report answers, with the empty pair in it.

    Without the `NULLIF` this raises on PostgreSQL and quietly returns NULL on SQLite — so the test
    that would have caught it only fails on one of the two engines the demos run on.
    """
    _seed(session)

    ratios = dict(selectors.reserved_ratio(session))

    assert set(ratios) == {"Committed", "Free", "Empty"}


def test_the_empty_pair_has_NO_ratio_rather_than_a_zero(session: SnakeSession) -> None:
    """`None` and not `0.0`, and the difference is the whole reason it is `NULLIF` and not `COALESCE`.

    Zero would say "nothing of it is promised", which reads as a pair with stock going spare. There
    is no stock: the fraction does not exist. This is the case where NULL is the honest answer, and
    the empty warehouse two files over is the case where zero is — same domain, opposite calls.
    """
    _seed(session)

    ratios = dict(selectors.reserved_ratio(session))

    assert ratios["Empty"] is None


def test_the_pairs_that_hold_something_report_their_fraction(
    session: SnakeSession,
) -> None:
    """The rows that always worked keep their number, in the units the engines agree on.

    Ninety per cent, as an `int`. A `reserved / on_hand` here would be integer division and answer
    `0` on both engines — the failure with no run that reveals it, which is why the fragment
    multiplies by a hundred first.
    """
    _seed(session)

    ratios = dict(selectors.reserved_ratio(session))

    assert ratios["Committed"] == 90
    assert ratios["Free"] == 0


def test_it_is_ONE_statement(session: SnakeSession) -> None:
    """The division happens in the engine, so the count does not grow with the pairs."""
    from snakeorm.debug import capture_queries

    _seed(session)

    with capture_queries() as collector:
        selectors.reserved_ratio(session)

    assert collector.report().count == 1, collector.report().to_text()


def test_WITHOUT_the_nullif_postgres_refuses_the_same_query(
    postgres_drivers: tuple[SnakeDriver, SnakeDriver],
) -> None:
    """The claim in this file's docstring, demonstrated against a real PostgreSQL.

    Everything else here runs on the in-memory SQLite the suite uses, and SQLite is the engine that
    answers NULL in silence — so on SQLite alone the bare division looks fine and the `NULLIF` reads
    as superstition. This is the run where it does not.

    It asks the DRIVER and not the session on purpose: what is being pinned is what the ENGINE does
    with the division, and the builder is the thing this justifies.
    """
    driver, _ = postgres_drivers

    with pytest.raises(Exception, match="division by zero"):
        driver.fetch_all("SELECT 10 / 0", ())


def test_WITH_the_nullif_postgres_answers_null(
    postgres_drivers: tuple[SnakeDriver, SnakeDriver],
) -> None:
    """And with it, the same server answers what SQLite answered all along: nothing, calmly."""
    driver, _ = postgres_drivers

    rows = driver.fetch_all("SELECT 10 / NULLIF(0, 0)", ())

    assert rows[0][0] is None
