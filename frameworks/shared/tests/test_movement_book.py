"""The movement book: TWO origins in one ledger, where a duplicate IS a fact.

TWO SYSTEMS WRITE INTO THE MOVEMENTS OF A WAREHOUSE, and the domain has said so since `receive` and
`ship` were written. The FLOOR writes when goods arrive and when a physical count corrects the shelf
(`purchase`, `adjustment`); the SHOP writes when an order takes units and when a customer sends them
back (`sale`, `return`). The book is what an operator reads to see both, and it prints the last few
lines of EACH — the busiest origin does not get to push the other off the page. That bound belongs
to a sort and no `WHERE` expresses it, which is what keeps the compound from being an `OR` in
disguise; it is the same argument `order_highlights` makes for `union`, from the other side.

AND FROM THE OTHER SIDE IS THE POINT. `union` is what the order report wants, because an order that
is both the biggest and the newest is ONE row of the answer. A book is the opposite: two units of
the same SKU leaving the same warehouse at the same instant are two orders, and a `UNION` folds them
into one line and leaves the book disagreeing with the stock by a unit. Losing a row is not a
cheaper answer, it is a wrong one.

WHY THIS NEEDED A VIEW, AND IT IS THE PART WORTH READING TWICE. Over a TABLE the fold cannot happen
at all: `only()` puts the primary key back whether it was named or not and `defer()` refuses to drop
it — a row that can be written has to keep its identity — so every projection of `stock_movements`
is unique by construction and `union` has nothing to remove. A `union_all` over that table would be
a cheaper spelling of `union` and nothing more, which is exactly what this repository's coverage
tally already said. `stock_ledger` is the same rows read as FACTS: a read-only view, no primary key,
and `defer(StockLedger.id)` therefore allowed. That difference is what makes the choice of operator
mean something, and the test below is the one that could not be written before.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from snakeorm import SnakeQuery, SnakeSession, SnakeUtc

from shared.models import (
    MovementReason,
    Sku,
    Stock,
    StockLedger,
    StockMovement,
    Warehouse,
)
from shared.selectors import inventory_selectors as selectors
from shared.usecases import inventory_usecases as usecases

WHEN = SnakeUtc(2026, 3, 1, 9, 0, tzinfo=dt.timezone.utc)
"""The instant the two identical events share. Written down so the premise is not left to a clock."""


def _shelf(session: SnakeSession) -> tuple[int, int]:
    """One warehouse, one SKU and the stock row the movements hang off. Returns the pair."""
    warehouse = session.add(
        Warehouse(
            code="BOK",
            name="Book",
            opened_on=dt.date(2020, 1, 1),
            shift_start=dt.time(6, 30),
            cutoff=dt.time(18, 0, tzinfo=dt.timezone.utc),
        )
    )
    sku = session.add(
        Sku(
            name="Widget",
            price=Decimal("9.99"),
            weight_kg=1.5,
            lead_time=dt.timedelta(days=3),
            attrs={},
            related_ids=[],
        )
    )
    session.commit()
    session.add(
        Stock(
            warehouse_id=warehouse.id,
            sku_id=sku.id,
            on_hand=100,
            counted_at=None,
            counted_local=None,
        )
    )
    session.commit()
    return warehouse.id, sku.id


def _event(
    session: SnakeSession,
    pair: tuple[int, int],
    *,
    delta: int,
    reason: MovementReason,
    when: SnakeUtc = WHEN,
) -> None:
    """One movement, at an instant the caller decides.

    `happened_at` is server-defaulted, so nobody passes one to the constructor; setting it before the
    write is how the seeder spreads a history, and here it is how two events become identical.
    """
    movement = StockMovement(
        stock_warehouse_id=pair[0],
        stock_sku_id=pair[1],
        delta=delta,
        reason=reason,
        note=None,
    )
    movement.happened_at = when
    session.add(movement)


def test_a_movement_row_keeps_its_identity_and_a_ledger_line_has_none() -> None:
    """The asymmetry the whole page rests on: `defer(id)` is refused on the table, allowed on the view.

    A table row must stay writable, so the ORM will not build one without its key. A view is
    read-only and has no key to preserve, so what comes back is the LINE — and only then can two
    events be the same answer twice.
    """
    with pytest.raises(Exception, match="primary key cannot be deferred"):
        SnakeQuery(StockMovement).defer(StockMovement.id)

    line = SnakeQuery(StockLedger).defer(StockLedger.id)

    assert line.projected_columns is not None
    assert "id" not in line.projected_columns


def test_two_identical_events_are_two_lines_and_a_union_would_print_one(
    postgres_pair: tuple[SnakeSession, SnakeSession],
) -> None:
    """THE proof, against a real engine: `union_all` answers TWO and `union` answers ONE.

    Two units of one SKU leave one warehouse at one instant. They are two shipments, so the book has
    two lines to print; the counterfactual below builds the SAME two branches with `union` and gets
    one. That missing line is a unit of stock the book cannot account for, and nothing anywhere
    would have said so.

    It runs on Postgres because the branches carry their own `LIMIT`, which needs parentheses SQLite
    refuses — the fold that answers there is tested separately, and it must not deduplicate either.
    """
    session, _ = postgres_pair
    pair = _shelf(session)
    _event(session, pair, delta=-1, reason=MovementReason.SALE)
    _event(session, pair, delta=-1, reason=MovementReason.SALE)
    _event(session, pair, delta=20, reason=MovementReason.PURCHASE)
    session.commit()

    shop, floor = selectors.book_branches(10)
    every = session.all(shop.union_all(floor))
    deduplicated = session.all(shop.union(floor))

    assert sorted(line.delta for line in every) == [-1, -1, 20]
    assert sorted(line.delta for line in deduplicated) == [-1, 20], (
        "UNION folded the two shipments into one line: a unit of stock the book cannot account for"
    )


def test_the_same_two_events_are_ONE_row_apart_on_the_table(
    postgres_pair: tuple[SnakeSession, SnakeSession],
) -> None:
    """The other half of the argument: over `stock_movements` the fold cannot happen at all.

    The key travels on every projection, so the two shipments differ by `id` and `union` removes
    nothing. That is why a `union_all` over the table would be a cheaper spelling of `union` and not
    a different answer — and why the book reads the view.
    """
    session, _ = postgres_pair
    pair = _shelf(session)
    _event(session, pair, delta=-1, reason=MovementReason.SALE)
    _event(session, pair, delta=-1, reason=MovementReason.SALE)
    session.commit()

    sales = SnakeQuery(StockMovement).filter(
        StockMovement.reason == MovementReason.SALE
    )
    returns = SnakeQuery(StockMovement).filter(
        StockMovement.reason == MovementReason.RETURN
    )

    assert len(session.all(sales.union_all(returns))) == 2
    assert len(session.all(sales.union(returns))) == 2


def test_the_book_prints_both_origins(session: SnakeSession) -> None:
    """The page's question: what the shop wrote and what the floor wrote, in one book."""
    pair = _shelf(session)
    _event(session, pair, delta=-1, reason=MovementReason.SALE)
    _event(session, pair, delta=20, reason=MovementReason.PURCHASE)
    _event(session, pair, delta=2, reason=MovementReason.RETURN)
    _event(session, pair, delta=-3, reason=MovementReason.ADJUSTMENT)
    session.commit()

    book = usecases.movement_book(session)

    assert sorted(line.reason.value for line in book) == [
        "adjustment",
        "purchase",
        "return",
        "sale",
    ]


def test_the_fold_that_answers_on_sqlite_keeps_the_duplicate_too(
    session: SnakeSession,
) -> None:
    """SQLite takes the two-statement path, and the Python half must not fold what SQL would not.

    A fold written as a set —which is what `fold_highlights` is for the order report— would silently
    reintroduce the deduplication on the one engine that cannot run the compound, and the book would
    then say two different things depending on where the demo is pointed.
    """
    assert session.dialect.supports_parenthesised_compound is False
    pair = _shelf(session)
    _event(session, pair, delta=-1, reason=MovementReason.SALE)
    _event(session, pair, delta=-1, reason=MovementReason.SALE)
    session.commit()

    book = usecases.movement_book(session)

    assert [line.delta for line in book] == [-1, -1]


def test_each_origin_is_bounded_on_its_OWN(session: SnakeSession) -> None:
    """The bound that makes this a compound and not an `OR`: the busy origin cannot crowd the other out.

    Six shipments and one delivery, with the book showing two lines per origin: a single `WHERE` with
    one `LIMIT` over the lot would print six sales and no delivery at all.
    """
    pair = _shelf(session)
    for index in range(6):
        _event(
            session,
            pair,
            delta=-1,
            reason=MovementReason.SALE,
            when=SnakeUtc(2026, 3, 1, 9, index, tzinfo=dt.timezone.utc),
        )
    _event(session, pair, delta=20, reason=MovementReason.PURCHASE)
    session.commit()

    book = usecases.movement_book(session, size=2)

    assert sorted(line.reason.value for line in book) == ["purchase", "sale", "sale"]
