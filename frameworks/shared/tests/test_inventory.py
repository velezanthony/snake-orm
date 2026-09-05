"""The inventory domain end to end: CRUD, the composite key and every type it declares.

These run against the shared in-memory SQLite, which is the engine that degrades the most — a
`Decimal` is TEXT there, a `list` is JSON, a `UUID` has no type. That is the point rather than a
compromise: if the value comes back EQUAL and of the DECLARED type on the engine that stores none of
them natively, the coercion is doing its job and not the database.

What is being pinned here is the shape the other seven domains could not reach. Stock is identified
by a PAIR, so it takes an upsert with two conflict columns, a `get` with two filters, and a to-many
whose foreign key carries two placeholders per parent.
"""

from __future__ import annotations

from datetime import date, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from typing import Any, cast

import pytest
from snakeorm import SnakeSession
from snakeorm.core.exceptions import (
    SnakeRelationshipNotLoaded,
    SnakeUnsupportedFeature,
)

from shared.dto.inventory_dto import (
    stock_dict,
    stock_page_dict,
    stock_with_relations_dict,
)
from shared.models import MovementReason, SkuKind
from shared.usecases import inventory_usecases as usecases
from shared.usecases.result import Failure

_THUMBNAIL = b"\x89PNG\r\n\x1a\n\x00\xff"


def _warehouse(session: SnakeSession, code: str = "MAD") -> int:
    warehouse = usecases.create_warehouse(
        session,
        code=code,
        name=f"Warehouse {code}",
        opened_on=date(2020, 3, 14),
        shift_start=time(6, 30),
        cutoff=time(18, 0, tzinfo=timezone(timedelta(hours=1))),
    )
    assert not isinstance(warehouse, Failure)
    return warehouse.id


def _sku(session: SnakeSession, name: str = "Widget") -> int:
    sku = usecases.create_sku(
        session,
        name=name,
        kind=SkuKind.PHYSICAL,
        price=Decimal("19.99"),
        weight_kg=2.5,
        lead_time=timedelta(days=3, hours=4),
        attrs={"colour": "red", "sizes": [1, 2, 3]},
        related_ids=[7, 11],
        thumbnail=_THUMBNAIL,
    )
    assert not isinstance(sku, Failure)
    return sku.id


def test_every_declared_type_comes_back_equal_and_typed(session: SnakeSession) -> None:
    """A SKU carries ten types; each one comes back EQUAL and as the type that was declared."""
    sku_id = _sku(session)

    sku = usecases.list_skus(session)[0]

    assert sku.id == sku_id
    assert isinstance(sku.public_id, UUID)
    assert sku.kind is SkuKind.PHYSICAL
    assert sku.price == Decimal("19.99") and isinstance(sku.price, Decimal)
    assert sku.weight_kg == 2.5
    assert sku.lead_time == timedelta(days=3, hours=4)
    assert sku.thumbnail == _THUMBNAIL
    assert sku.attrs == {"colour": "red", "sizes": [1, 2, 3]}
    assert sku.related_ids == [7, 11]


def test_the_warehouse_carries_its_date_time_and_boolean(session: SnakeSession) -> None:
    """`date`, `time` and `bool` survive the round trip on the engine that has none of them."""
    _warehouse(session)

    warehouse = usecases.list_warehouses(session)[0]

    assert warehouse.opened_on == date(2020, 3, 14)
    assert warehouse.shift_start == time(6, 30)
    assert warehouse.active is True


def test_the_inherited_column_comes_back_on_the_object_that_was_added(
    session: SnakeSession,
) -> None:
    """`created_at` is put in by the server AND reaches the instance, without reading the row again.

    The re-read is the weaker half and it used to be the only half: asking the database for the row
    afterwards proves the column has a value, which it would have even if the write had learnt
    nothing. What the wide `RETURNING` promises is that the object you were handed already carries
    it, and that promise is engine-shaped — this suite runs on SQLite, which has had the clause only
    since 3.35 and was the engine nobody exercised.
    """
    created = usecases.create_warehouse(
        session,
        code="RET",
        name="Warehouse RET",
        opened_on=date(2020, 3, 14),
        shift_start=time(6, 30),
        cutoff=time(18, 0, tzinfo=timezone(timedelta(hours=1))),
    )
    assert not isinstance(created, Failure)

    assert created.created_at is not None, (
        "the server filled `created_at` in and RETURNING did not bring it back"
    )
    assert created.id is not None

    stored = next(w for w in usecases.list_warehouses(session) if w.id == created.id)
    assert stored.created_at == created.created_at


def test_receiving_creates_the_pair_and_then_adds_to_it(session: SnakeSession) -> None:
    """The first receiving creates the stock row; the second one adds to the same pair."""
    warehouse_id, sku_id = _warehouse(session), _sku(session)

    usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=10)
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=5)

    rows = usecases.stock_of_warehouse(session, warehouse_id)
    assert not isinstance(rows, Failure)
    assert [(row.warehouse_id, row.sku_id, row.on_hand) for row in rows] == [
        (warehouse_id, sku_id, 15)
    ]


def test_a_count_upserts_over_the_composite_key(session: SnakeSession) -> None:
    """Counting sets the pair whether or not it was there: one upsert, two conflict columns."""
    warehouse_id, sku_id = _warehouse(session), _sku(session)

    usecases.count_stock(session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=42)
    usecases.count_stock(session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=7)

    rows = usecases.stock_of_warehouse(session, warehouse_id)
    assert not isinstance(rows, Failure)
    assert [row.on_hand for row in rows] == [7]


def test_shipping_more_than_there_is_writes_nothing(session: SnakeSession) -> None:
    """The rule is checked before writing, so there is nothing to undo and no movement is recorded."""
    warehouse_id, sku_id = _warehouse(session), _sku(session)
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=4)

    refused = usecases.ship(session, warehouse_id=warehouse_id, sku_id=sku_id, units=9)

    assert refused == Failure("conflict")
    movements = usecases.movements_of(session, warehouse_id, sku_id)
    assert not isinstance(movements, Failure)
    assert [movement.delta for movement in movements] == [4]


def test_shipping_records_why_the_stock_moved(session: SnakeSession) -> None:
    """A quantity that changed with no movement behind it is stock nobody can explain."""
    warehouse_id, sku_id = _warehouse(session), _sku(session)
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=10)

    usecases.ship(session, warehouse_id=warehouse_id, sku_id=sku_id, units=3)

    movements = usecases.movements_of(session, warehouse_id, sku_id)
    assert not isinstance(movements, Failure)
    assert {(m.delta, m.reason) for m in movements} == {
        (10, MovementReason.PURCHASE),
        (-3, MovementReason.SALE),
    }


def test_the_movements_of_several_pairs_load_in_one_select_in(
    session: SnakeSession,
) -> None:
    """The to-many over a COMPOSITE foreign key is ONE extra statement, not one per parent.

    This is the shape that made the select-in's batching worth measuring in placeholders: two columns
    per parent, so the same ceiling holds half as many parents.
    """
    warehouse_id = _warehouse(session)
    for index in range(4):
        sku_id = _sku(session, name=f"Widget {index}")
        usecases.receive(
            session, warehouse_id=warehouse_id, sku_id=sku_id, units=index + 1
        )

    rows = usecases.stock_with_movements(session, warehouse_id)

    assert not isinstance(rows, Failure)
    assert [len(row.movements) for row in rows] == [1, 1, 1, 1]


def test_the_stats_come_typed_and_in_one_statement(session: SnakeSession) -> None:
    """`annotate` gives back the warehouse plus its aggregates, typed, with no query per row."""
    warehouse_id = _warehouse(session)
    for index in range(3):
        sku_id = _sku(session, name=f"Widget {index}")
        usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=10)

    stats = usecases.warehouse_stats(session)

    assert [(s.sku_count, s.total_units) for s in stats] == [(3, 30)]


def test_reserving_touches_every_row_in_one_statement(session: SnakeSession) -> None:
    """A bulk write: the arithmetic travels to the engine and no instance is loaded."""
    warehouse_id = _warehouse(session)
    for index in range(3):
        sku_id = _sku(session, name=f"Widget {index}")
        usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=10)

    touched = usecases.reserve(session, warehouse_id=warehouse_id, units=2)

    assert touched == 3
    rows = usecases.stock_of_warehouse(session, warehouse_id)
    assert not isinstance(rows, Failure)
    assert [row.reserved for row in rows] == [2, 2, 2]


def test_an_unknown_warehouse_is_not_found_rather_than_empty(
    session: SnakeSession,
) -> None:
    """Asking about something that is not there is a `not_found`, not an empty list."""
    assert usecases.stock_of_warehouse(session, 999) == Failure("not_found")
    assert usecases.get_warehouse(session, 999) == Failure("not_found")


def test_the_view_answers_only_what_is_running_out(session: SnakeSession) -> None:
    """The threshold lives in the DATABASE: the view is the definition of "running out"."""
    warehouse_id = _warehouse(session)
    scarce, plenty = _sku(session, "Scarce"), _sku(session, "Plenty")
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=scarce, units=3)
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=plenty, units=99)

    rows = usecases.low_stock(session)

    assert [row.sku_id for row in rows] == [scarce]
    assert rows[0].warehouse_id == warehouse_id


def test_the_view_refuses_to_be_written_to(session: SnakeSession) -> None:
    """A read model that CANNOT be written to is a different guarantee from one that happens not to.

    The checker refuses first — `session.add` wants a `SnakeModel` and a view is not one — so the
    cast is what it takes to even reach the runtime lock. Both halves exist on purpose: the type
    stops it while writing the code, and this stops it when somebody silences the type.
    """
    warehouse_id = _warehouse(session)
    sku_id = _sku(session)
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=1)
    row = usecases.low_stock(session)[0]

    with pytest.raises(SnakeUnsupportedFeature):
        session.add(cast("Any", row))


def test_correcting_a_pair_writes_both_levels_and_no_movement(
    session: SnakeSession,
) -> None:
    """An audit correction is not a reason stock moved: it edits the row and writes no history.

    Conflating the two is how an audit trail fills up with purchases that never happened, which is
    the one thing the trail exists to make impossible.
    """
    warehouse_id, sku_id = _warehouse(session), _sku(session)
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=10)

    usecases.update_stock(
        session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=8, reserved=2
    )

    rows = usecases.stock_of_warehouse(session, warehouse_id)
    assert not isinstance(rows, Failure)
    assert [(row.on_hand, row.reserved) for row in rows] == [(8, 2)]
    movements = usecases.movements_of(session, warehouse_id, sku_id)
    assert not isinstance(movements, Failure)
    assert [movement.delta for movement in movements] == [10]


def test_correcting_a_pair_that_is_not_there_does_not_create_it(
    session: SnakeSession,
) -> None:
    """`update` is not an upsert: a row deleted between drawing the form and posting it is a 404."""
    warehouse_id, sku_id = _warehouse(session), _sku(session)

    refused = usecases.update_stock(
        session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=5, reserved=0
    )

    assert refused == Failure("not_found")
    rows = usecases.stock_of_warehouse(session, warehouse_id)
    assert not isinstance(rows, Failure)
    assert rows == []


def test_a_negative_level_is_refused_before_the_engine_sees_it(
    session: SnakeSession,
) -> None:
    """The CHECK holds under two writers; this holds so the form gets an answer, not a driver error."""
    warehouse_id, sku_id = _warehouse(session), _sku(session)
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=10)

    refused = usecases.update_stock(
        session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=-1, reserved=0
    )

    assert refused == Failure("missing_fields")


def test_a_pair_with_history_is_not_deleted_but_refused(session: SnakeSession) -> None:
    """FK RESTRICT, said in the ORM's own words: the movements are why the numbers ever changed.

    The engine would refuse anyway, with a driver error raised inside a commit three layers under
    the page that asked. Refusing first is what lets a delete page explain itself.
    """
    warehouse_id, sku_id = _warehouse(session), _sku(session)
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=10)

    refused = usecases.remove_stock(session, warehouse_id=warehouse_id, sku_id=sku_id)

    assert refused == Failure("conflict")
    rows = usecases.stock_of_warehouse(session, warehouse_id)
    assert not isinstance(rows, Failure)
    assert len(rows) == 1


def test_a_pair_that_never_moved_can_be_deleted(session: SnakeSession) -> None:
    """A count creates the row without a movement, so that pair has nothing to orphan."""
    warehouse_id, sku_id = _warehouse(session), _sku(session)
    usecases.count_stock(session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=4)

    removed = usecases.remove_stock(session, warehouse_id=warehouse_id, sku_id=sku_id)

    assert removed is None
    rows = usecases.stock_of_warehouse(session, warehouse_id)
    assert not isinstance(rows, Failure)
    assert rows == []


def test_deleting_a_pair_that_is_not_there_says_so(session: SnakeSession) -> None:
    """`not_found` and not a silent success: a delete that deleted nothing is worth knowing about."""
    warehouse_id = _warehouse(session)

    assert usecases.remove_stock(
        session, warehouse_id=warehouse_id, sku_id=999
    ) == Failure("not_found")


def test_the_pair_serialiser_names_the_warehouse_and_the_sku(
    session: SnakeSession,
) -> None:
    """The with-relations document carries both hops, and the bare one carries neither.

    `get_stock` loads the warehouse and the SKU in the same statement, and the whole reason it does
    is so a client gets the CODE and the NAME rather than two ids and two more requests. The bare
    keys are asserted alongside because the pair is what identifies the row: the names are extra,
    never a replacement.
    """
    warehouse_id, sku_id = _warehouse(session), _sku(session)
    usecases.count_stock(session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=12)

    stock = usecases.get_stock(session, warehouse_id, sku_id)

    assert not isinstance(stock, Failure)
    document = stock_with_relations_dict(stock)
    assert document["warehouse_id"] == warehouse_id and document["sku_id"] == sku_id
    assert document["warehouse"] == "MAD" and document["sku"] == "Widget"
    assert set(stock_dict(stock)) & {"warehouse", "sku"} == set()


def test_the_bare_pair_serialiser_is_the_only_one_a_bare_read_may_use(
    session: SnakeSession,
) -> None:
    """The split into two serialisers is load-bearing, and this is what makes it fail loudly.

    A row fetched without its relations has no warehouse and no SKU to name, and the ORM says so
    instead of guessing. Handing such a row to the with-relations serialiser raises HERE, in a test,
    rather than half-way through writing a response — where the transaction is over, the status line
    has gone and what the client sees is a 500 for a row that exists.
    """
    warehouse_id, sku_id = _warehouse(session), _sku(session)
    usecases.count_stock(session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=12)

    bare = usecases.stock_of_warehouse(session, warehouse_id)

    assert not isinstance(bare, Failure)
    assert stock_dict(bare[0])["on_hand"] == 12
    with pytest.raises(SnakeRelationshipNotLoaded, match="warehouse"):
        stock_with_relations_dict(bare[0])


def test_the_stock_page_document_carries_its_pager(session: SnakeSession) -> None:
    """Rows, total, page and pages travel in ONE document, and the rows carry both hops.

    Splitting them is how a pager ends up saying 3 over a listing that shows a different 3, and the
    document is the only place that can refuse to split them. The clamped page comes back rather
    than the one that was asked for — 9 was asked for and there are two — because the number arrived
    from a URL.

    The rows are held against `stock_with_relations_dict` and not merely inspected, which is the
    assertion with teeth: `paginate_stock` pays for two JOINs, and a page serialised with the bare
    `stock_dict` would answer the same four keys, the same total and the same ids while quietly
    dropping what the JOINs were for.
    """
    warehouse_id = _warehouse(session)
    for index in range(3):
        sku_id = _sku(session, name=f"Widget {index}")
        usecases.count_stock(
            session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=index + 1
        )

    page = usecases.paginate_stock(
        session, warehouse_id=warehouse_id, page=9, per_page=2
    )

    document = stock_page_dict(page)

    assert set(document) == {"rows", "total", "page", "pages"}
    assert (document["total"], document["page"], document["pages"]) == (3, 2, 2)
    assert document["rows"] == [stock_with_relations_dict(row) for row in page.rows]
    assert [row.sku.name for row in page.rows] == ["Widget 2"]
