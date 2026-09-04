"""The view models of `inventory`: that the page shape is flat, primitive and costs a fixed number
of queries.

Three things are being pinned here, and each one is a way the presentation layer has already gone
wrong somewhere.

The first is that NOTHING but a primitive leaves this layer. A template that reaches for
`stock.sku.name` is loading a relation inside the renderer, where no `assert_queries` is watching:
it works today because the selector did the `include`, and the day somebody drops that `include` the
page still paints — one query per row. So the test walks the returned dict to its leaves and refuses
anything that is not a `str`, an `int`, a `bool` or `None`. A model instance in there is a loaded
relation waiting to happen; a `datetime` or a `Decimal` in there is a formatting decision that has
escaped into the HTML, where the two demos would each make it differently.

The second is the ARITHMETIC of pagination, which is the part that looks trivial and is not: a page
number that walks past the end, a `has_next` on the last page, an off-by-one in the slice. All three
are invisible until somebody clicks.

The third is the query BUDGET. A list page must cost the same whether it shows three rows or thirty,
and that number is asserted at two row counts rather than written down once: a constant compared
against itself is what catches an N+1, and a constant compared against a literal only catches a
rewrite.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from snakeorm import SnakeModel, SnakeSession
from snakeorm.debug import capture_queries

from shared.models import SkuKind
from shared.usecases import inventory_usecases as usecases
from shared.usecases.result import Failure
from shared.viewmodels import inventory_viewmodels as viewmodels

# What a template is allowed to receive. `bool` is listed for the reader even though it is an `int`.
_PRIMITIVES = (str, int, bool, type(None))


def _leaves(value: object) -> Iterator[object]:
    """Every leaf of a page dict, walking through the dicts and lists it nests.

    It has to recurse: the shapes here carry lists of rows, and a `Decimal` three levels down is the
    one that would reach the template unnoticed. A shallow check over `page.values()` would call a
    list of model instances "a list" and pass.
    """
    if isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _leaves(item)
    else:
        yield value


def _assert_only_primitives(page: object) -> None:
    """Asserts that the whole page is made of primitives, naming the offender when it is not."""
    for leaf in _leaves(page):
        assert not isinstance(leaf, SnakeModel), (
            f"a model reached the template: {leaf!r}"
        )
        assert not isinstance(leaf, (datetime, date)), f"an unformatted date: {leaf!r}"
        assert not isinstance(leaf, Decimal), f"an unformatted decimal: {leaf!r}"
        assert isinstance(leaf, _PRIMITIVES), f"not a primitive: {type(leaf)} {leaf!r}"


def _warehouse(session: SnakeSession, code: str = "MAD") -> int:
    """A warehouse, by its use case, so the row is exactly the one a demo would have written."""
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
    """A SKU with a price, because the price is the value the page has to format rather than emit."""
    sku = usecases.create_sku(
        session,
        name=name,
        kind=SkuKind.PHYSICAL,
        price=Decimal("19.99"),
        weight_kg=2.5,
        lead_time=timedelta(days=3),
        attrs={},
        related_ids=[],
    )
    assert not isinstance(sku, Failure)
    return sku.id


def _stocked(session: SnakeSession, warehouse_id: int, how_many: int) -> list[int]:
    """`how_many` SKUs received into the warehouse, returning their ids in creation order.

    Receiving rather than inserting: it is the path that also writes the movement, which is what the
    detail and the delete-confirmation pages read.
    """
    sku_ids: list[int] = []
    for index in range(how_many):
        sku_id = _sku(session, name=f"Widget {index:02d}")
        usecases.receive(
            session, warehouse_id=warehouse_id, sku_id=sku_id, units=index + 1
        )
        sku_ids.append(sku_id)
    return sku_ids


# ---- Only primitives come out ------------------------------------------------------------------


def test_the_list_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The listing hands the template strings and numbers, never a `Stock` nor its warehouse."""
    warehouse_id = _warehouse(session)
    _stocked(session, warehouse_id, 3)

    page = viewmodels.stock_list(session)

    _assert_only_primitives(page)


def test_the_detail_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The detail navigates two to-one relations and a to-many, and none of the three leaks out."""
    warehouse_id = _warehouse(session)
    sku_id = _stocked(session, warehouse_id, 1)[0]

    page = viewmodels.stock_detail(session, warehouse_id, sku_id)

    assert not isinstance(page, Failure)
    _assert_only_primitives(page)


def test_the_form_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The form's options carry a price, which is a `Decimal` until this layer formats it."""
    warehouse_id = _warehouse(session)
    sku_id = _stocked(session, warehouse_id, 2)[0]

    page = viewmodels.stock_form(session, warehouse_id, sku_id)

    assert not isinstance(page, Failure)
    _assert_only_primitives(page)


def test_the_delete_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The confirmation counts what would go with the row, and a count is already a number."""
    warehouse_id = _warehouse(session)
    sku_id = _stocked(session, warehouse_id, 1)[0]

    page = viewmodels.stock_delete_confirm(session, warehouse_id, sku_id)

    assert not isinstance(page, Failure)
    _assert_only_primitives(page)


# ---- The relation navigation the template no longer does ---------------------------------------


def test_the_row_carries_the_warehouse_and_the_sku_already_flattened(
    session: SnakeSession,
) -> None:
    """`warehouse_code` and `sku_name` come from two to-one hops made HERE, not in the HTML."""
    warehouse_id = _warehouse(session)
    sku_id = _stocked(session, warehouse_id, 1)[0]

    row = viewmodels.stock_list(session)["rows"][0]

    assert row["warehouse_code"] == "MAD"
    assert row["warehouse_name"] == "Warehouse MAD"
    assert row["sku_name"] == "Widget 00"
    assert row["sku_kind"] == "physical"
    assert (row["warehouse_id"], row["sku_id"]) == (warehouse_id, sku_id)


def test_available_is_computed_and_not_left_to_the_template(
    session: SnakeSession,
) -> None:
    """`quantity - reserved` is one subtraction, and two templates would write it two ways."""
    warehouse_id = _warehouse(session)
    sku_id = _sku(session)
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=10)
    usecases.reserve(session, warehouse_id=warehouse_id, units=3)

    row = viewmodels.stock_list(session)["rows"][0]

    assert (row["on_hand"], row["reserved"], row["available"]) == (10, 3, 7)


def test_a_missing_count_reads_as_empty_rather_than_none(session: SnakeSession) -> None:
    """`counted_at` is nullable, and `None` in a template prints the word "None"."""
    warehouse_id = _warehouse(session)
    _stocked(session, warehouse_id, 1)

    row = viewmodels.stock_list(session)["rows"][0]

    assert row["counted_at"] == ""


# ---- The composite key survives the round trip -------------------------------------------------


def test_the_composite_key_survives_the_round_trip(session: SnakeSession) -> None:
    """Both halves go into the call and both come back out: the pair IS the identity.

    This is the check the plan asks the pilot for. A page keyed by a pair is where a demo would lose
    half the key —in the URL, in the form, in the redirect— and still look right, because the other
    half alone finds a row.
    """
    warehouse_id = _warehouse(session)
    sku_id = _stocked(session, warehouse_id, 1)[0]

    page = viewmodels.stock_detail(session, warehouse_id, sku_id)

    assert not isinstance(page, Failure)
    assert page["stock"]["warehouse_id"] == warehouse_id
    assert page["stock"]["sku_id"] == sku_id


def test_a_pair_that_does_not_exist_is_a_failure_and_not_an_empty_page(
    session: SnakeSession,
) -> None:
    """The web layer needs a 404, and an empty page is a 200 that says nothing is wrong."""
    warehouse_id = _warehouse(session)
    sku_id = _stocked(session, warehouse_id, 1)[0]

    assert viewmodels.stock_detail(session, warehouse_id, 999) == Failure("not_found")
    assert viewmodels.stock_detail(session, 999, sku_id) == Failure("not_found")
    assert viewmodels.stock_delete_confirm(session, 999, sku_id) == Failure("not_found")
    assert viewmodels.stock_form(session, 999, sku_id) == Failure("not_found")


def test_half_a_key_is_not_a_key(session: SnakeSession) -> None:
    """Two warehouses holding the SAME sku: the row that comes back is the one asked for.

    With a single warehouse in the database, dropping `warehouse_id` from the lookup passes anyway.
    This is the arrangement where it cannot.
    """
    first, second = _warehouse(session, "MAD"), _warehouse(session, "BCN")
    sku_id = _sku(session)
    usecases.receive(session, warehouse_id=first, sku_id=sku_id, units=5)
    usecases.receive(session, warehouse_id=second, sku_id=sku_id, units=9)

    page = viewmodels.stock_detail(session, second, sku_id)

    assert not isinstance(page, Failure)
    assert page["stock"]["warehouse_id"] == second
    assert page["stock"]["on_hand"] == 9


# ---- Pagination ---------------------------------------------------------------------------------


def test_the_middle_page_has_a_previous_and_a_next(session: SnakeSession) -> None:
    """Seven rows at three per page is three pages, and the second one is surrounded."""
    warehouse_id = _warehouse(session)
    _stocked(session, warehouse_id, 7)

    page = viewmodels.stock_list(session, page=2, per_page=3)

    assert (page["total"], page["pages"], page["page"]) == (7, 3, 2)
    assert (page["has_prev"], page["has_next"]) == (True, True)
    assert (page["prev_page"], page["next_page"]) == (1, 3)


def test_the_middle_page_carries_the_middle_slice(session: SnakeSession) -> None:
    """The rows of page two are the fourth, fifth and sixth: an off-by-one here is invisible."""
    warehouse_id = _warehouse(session)
    sku_ids = _stocked(session, warehouse_id, 7)

    page = viewmodels.stock_list(session, page=2, per_page=3)

    assert [row["sku_id"] for row in page["rows"]] == sku_ids[3:6]


def test_the_edges_do_not_offer_a_step_that_does_not_exist(
    session: SnakeSession,
) -> None:
    """First page has no previous, last page has no next, and the last one is not full."""
    warehouse_id = _warehouse(session)
    _stocked(session, warehouse_id, 7)

    first = viewmodels.stock_list(session, page=1, per_page=3)
    last = viewmodels.stock_list(session, page=3, per_page=3)

    assert (first["has_prev"], first["has_next"]) == (False, True)
    assert (last["has_prev"], last["has_next"]) == (True, False)
    assert len(last["rows"]) == 1


def test_a_page_past_the_end_lands_on_the_last_one(session: SnakeSession) -> None:
    """A page number comes from the URL, so it is whatever somebody typed there.

    Clamping instead of answering an empty page is the useful behaviour: `?page=99` is a stale
    bookmark, and a blank listing reads as "there is nothing here" when there are seven rows.
    """
    warehouse_id = _warehouse(session)
    _stocked(session, warehouse_id, 7)

    page = viewmodels.stock_list(session, page=99, per_page=3)

    assert page["page"] == 3
    assert page["has_next"] is False
    assert len(page["rows"]) == 1


def test_an_empty_listing_is_still_one_page(session: SnakeSession) -> None:
    """Zero rows is `1 of 1`, not `1 of 0`: a pager that says page 1 of 0 is a division that leaked."""
    _warehouse(session)

    page = viewmodels.stock_list(session)

    assert (page["total"], page["pages"], page["page"]) == (0, 1, 1)
    assert (page["has_prev"], page["has_next"]) == (False, False)
    assert page["rows"] == []


def test_the_warehouse_filter_narrows_the_listing_and_comes_back(
    session: SnakeSession,
) -> None:
    """The filter travels back in the page so the template can mark the selected option."""
    first, second = _warehouse(session, "MAD"), _warehouse(session, "BCN")
    _stocked(session, first, 3)
    sku_id = _sku(session, "Only in BCN")
    usecases.receive(session, warehouse_id=second, sku_id=sku_id, units=4)

    page = viewmodels.stock_list(session, warehouse_id=second)

    assert page["warehouse_id"] == second
    assert page["total"] == 1
    assert [row["sku_id"] for row in page["rows"]] == [sku_id]
    assert [option["code"] for option in page["warehouses"]] == ["BCN", "MAD"]


# ---- The query budget ---------------------------------------------------------------------------


def _queries_of_a_list_page(session: SnakeSession, rows: int) -> int:
    """Builds a full list page over `rows` stock rows and returns how many statements it took."""
    warehouse_id = _warehouse(session)
    _stocked(session, warehouse_id, rows)
    with capture_queries() as collector:
        page = viewmodels.stock_list(session, per_page=rows + 1)
    assert len(page["rows"]) == rows, "the budget was measured over the wrong page"
    return collector.report().count


def test_the_list_page_costs_the_same_at_three_rows_and_at_thirty(
    make_session: Callable[[], SnakeSession],
) -> None:
    """The N+1 net: the cost of the listing must not depend on how many rows it shows.

    Two databases and not two pages of the same one, because the second measurement has to start
    from a clean slate. And the assertion is one count against the OTHER count rather than against a
    literal: a literal turns every legitimate rewrite of the query into a red test, and still passes
    the day the number happens to match. What must never change is the SLOPE.
    """
    small, large = make_session(), make_session()
    try:
        assert _queries_of_a_list_page(small, 3) == _queries_of_a_list_page(large, 30)
    finally:
        small.close()
        large.close()


def test_the_list_page_is_three_statements(session: SnakeSession) -> None:
    """And what that constant IS: count, page of rows, and the warehouses of the filter.

    The number is written down once, here, so that the day it moves somebody has to say why. The
    test above is what keeps it flat; this one is what keeps it small.
    """
    assert _queries_of_a_list_page(session, 5) == 3


def test_the_detail_page_costs_the_same_at_one_movement_and_at_twenty(
    session: SnakeSession,
) -> None:
    """The to-many over the COMPOSITE key is ONE extra statement, however many rows come back."""
    warehouse_id = _warehouse(session)
    quiet, busy = _sku(session, "Quiet"), _sku(session, "Busy")
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=quiet, units=1)
    for _ in range(20):
        usecases.receive(session, warehouse_id=warehouse_id, sku_id=busy, units=1)

    with capture_queries() as one:
        viewmodels.stock_detail(session, warehouse_id, quiet)
    with capture_queries() as many:
        page = viewmodels.stock_detail(session, warehouse_id, busy)

    assert not isinstance(page, Failure)
    assert len(page["movements"]) == 20
    assert one.report().count == many.report().count == 2


def test_the_delete_confirmation_counts_without_loading(session: SnakeSession) -> None:
    """It says how many movements would be dragged along, and a COUNT is not a fetch.

    Loading them to call `len()` is the version that works on the demo seed and falls over on a pair
    with a year of history, which is exactly the pair somebody would try to delete.
    """
    warehouse_id = _warehouse(session)
    sku_id = _sku(session)
    for _ in range(12):
        usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=1)

    with capture_queries() as collector:
        page = viewmodels.stock_delete_confirm(session, warehouse_id, sku_id)

    assert not isinstance(page, Failure)
    assert page["movement_count"] == 12
    assert collector.report().count == 2


# ---- The form, which is create and update at once ------------------------------------------------


def test_the_create_form_offers_the_options_and_holds_no_row(
    session: SnakeSession,
) -> None:
    """Creating means every warehouse and every SKU to choose from, and nothing selected yet."""
    _warehouse(session, "MAD")
    _warehouse(session, "BCN")
    _sku(session, "Widget A")
    _sku(session, "Widget B")

    page = viewmodels.stock_form(session)

    assert not isinstance(page, Failure)
    assert page["is_update"] is False
    assert page["stock"] is None
    assert [option["code"] for option in page["warehouses"]] == ["BCN", "MAD"]
    assert [option["name"] for option in page["skus"]] == ["Widget A", "Widget B"]


def test_the_update_form_carries_the_row_it_is_editing(session: SnakeSession) -> None:
    """The same page with a pair in it: same options, plus the values already in the row."""
    warehouse_id = _warehouse(session)
    sku_id = _stocked(session, warehouse_id, 1)[0]

    page = viewmodels.stock_form(session, warehouse_id, sku_id)

    assert not isinstance(page, Failure)
    assert page["is_update"] is True
    assert page["stock"] is not None
    assert page["stock"]["on_hand"] == 1


def test_half_a_pair_is_not_an_update(session: SnakeSession) -> None:
    """One id without the other cannot identify a row, so the form falls back to creating."""
    warehouse_id = _warehouse(session)
    _stocked(session, warehouse_id, 1)

    page = viewmodels.stock_form(session, warehouse_id, None)

    assert not isinstance(page, Failure)
    assert page["is_update"] is False
    assert page["stock"] is None


def test_the_price_is_formatted_here_and_not_in_the_template(
    session: SnakeSession,
) -> None:
    """Money leaves this layer as text with its two decimals, because a template cannot round.

    The DTO next door emits `str(price)` instead, and the difference is deliberate: JSON has to be
    exact because a machine reads it, and a page has to be legible because a person does.
    """
    _warehouse(session)
    _sku(session)

    page = viewmodels.stock_form(session)

    assert not isinstance(page, Failure)
    assert page["skus"][0]["price"] == "19.99"


def test_the_detail_page_formats_the_sku_and_warehouse_singletons(
    session: SnakeSession,
) -> None:
    """The UUID, the price and the opening date come out as text ready to print."""
    warehouse_id = _warehouse(session)
    sku_id = _stocked(session, warehouse_id, 1)[0]

    page = viewmodels.stock_detail(session, warehouse_id, sku_id)

    assert not isinstance(page, Failure)
    assert page["sku_price"] == "19.99"
    assert page["warehouse_opened_on"] == "2020-03-14"
    assert len(page["sku_public_id"]) == 36


def test_a_movement_reads_as_text_including_the_note_it_does_not_have(
    session: SnakeSession,
) -> None:
    """`reason` is an enum and `happened_at` a timestamp; both arrive as strings, `note` as empty."""
    warehouse_id = _warehouse(session)
    sku_id = _stocked(session, warehouse_id, 1)[0]

    page = viewmodels.stock_detail(session, warehouse_id, sku_id)

    assert not isinstance(page, Failure)
    movement = page["movements"][0]
    assert movement["reason"] == "purchase"
    assert movement["delta"] == 1
    assert movement["note"] == ""
    assert movement["happened_at"].startswith("20")


# ---- The reorder screen and the warehouse sheet -------------------------------------------------


def _levels(
    session: SnakeSession,
    warehouse_id: int,
    sku_id: int,
    *,
    on_hand: int,
    reserved: int,
) -> int:
    """A pair standing at those exact levels, brought there through the two use cases that do it.

    `count_stock` is the upsert that makes the pair exist and `update_stock` is what sets both
    numbers, which is the only path a page has to `reserved` at all — and going through it is what
    keeps this fixture from asserting over a row no demo could have written.
    """
    counted = usecases.count_stock(
        session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=on_hand
    )
    assert not isinstance(counted, Failure)
    updated = usecases.update_stock(
        session,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        on_hand=on_hand,
        reserved=reserved,
    )
    assert not isinstance(updated, Failure)
    return sku_id


def test_the_alerts_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The reorder screen hands the template strings and numbers, never a `LowStock` row."""
    warehouse_id = _warehouse(session)
    _levels(session, warehouse_id, _sku(session, "Short"), on_hand=3, reserved=0)

    page = viewmodels.low_stock_alerts(session)

    _assert_only_primitives(page)


def test_the_alerts_page_names_the_two_ids_the_view_carries(
    session: SnakeSession,
) -> None:
    """The view projects the PAIR and nothing either half points at, so the names come from lookups.

    This is the assertion that would break if somebody "simplified" the page into reading
    `row.warehouse.code`: a view is a query and not a graph, so there is no relation there to hop.
    """
    warehouse_id = _warehouse(session, "BCN")
    sku_id = _sku(session, "Short")
    _levels(session, warehouse_id, sku_id, on_hand=3, reserved=0)

    row = viewmodels.low_stock_alerts(session)["rows"][0]

    assert row["warehouse_id"] == warehouse_id and row["sku_id"] == sku_id
    assert row["warehouse_code"] == "BCN"
    assert row["warehouse_name"] == "Warehouse BCN"
    assert row["sku_name"] == "Short"
    assert row["lead_time_days"] == 3


def test_the_alert_is_raised_on_what_is_AVAILABLE_and_not_on_what_is_on_the_shelf(
    session: SnakeSession,
) -> None:
    """Fifty units of which forty-five are promised is FIVE, and five is running out.

    It is the pair the view used to stay silent about, back when the threshold read `on_hand`, and it
    is the whole reason this page is worth having: a shelf that looks full is not stock you can sell.
    The healthy pair beside it is what stops the assertion passing over a page that flags everything.
    """
    warehouse_id = _warehouse(session)
    promised = _levels(
        session, warehouse_id, _sku(session, "Promised"), on_hand=50, reserved=45
    )
    _levels(session, warehouse_id, _sku(session, "Healthy"), on_hand=50, reserved=0)

    page = viewmodels.low_stock_alerts(session)

    assert [row["sku_id"] for row in page["rows"]] == [promised]
    assert page["rows"][0]["available"] == 5
    assert page["alert_count"] == 1


def test_a_stockroom_in_good_order_is_an_empty_page_and_not_a_failure(
    session: SnakeSession,
) -> None:
    """Nothing running out is the answer everybody wants, so it cannot be a refusal."""
    warehouse_id = _warehouse(session)
    _levels(session, warehouse_id, _sku(session, "Healthy"), on_hand=200, reserved=1)

    page = viewmodels.low_stock_alerts(session)

    assert page == {"rows": [], "alert_count": 0}


def _queries_of_an_alerts_page(session: SnakeSession, alerts: int) -> int:
    """Builds the reorder screen over `alerts` short pairs and returns how many statements it took."""
    warehouse_id = _warehouse(session)
    for index in range(alerts):
        _levels(
            session,
            warehouse_id,
            _sku(session, f"Short {index:02d}"),
            on_hand=1,
            reserved=0,
        )
    with capture_queries() as collector:
        page = viewmodels.low_stock_alerts(session)
    assert page["alert_count"] == alerts, "the budget was measured over the wrong page"
    return collector.report().count


def test_the_alerts_page_costs_the_same_at_two_alerts_and_at_twenty(
    make_session: Callable[[], SnakeSession],
) -> None:
    """The N+1 net for the page whose rows carry ids that a naive fix would resolve one by one.

    Two databases, and one count against the OTHER rather than against a literal, for the reason the
    listing's twin gives: what must never change is the SLOPE.
    """
    small, large = make_session(), make_session()
    try:
        assert _queries_of_an_alerts_page(small, 2) == _queries_of_an_alerts_page(
            large, 20
        )
    finally:
        small.close()
        large.close()


def test_the_alerts_page_is_three_statements(session: SnakeSession) -> None:
    """And what that constant IS: the view, the warehouses and the SKUs the two ids are named from."""
    assert _queries_of_an_alerts_page(session, 4) == 3


def test_the_movement_book_is_made_of_primitives(session: SnakeSession) -> None:
    """The book hands the template strings and numbers, never a `StockLedger` line."""
    warehouse_id = _warehouse(session)
    sku_id = _sku(session, "Moved")
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=5)
    usecases.ship(session, warehouse_id=warehouse_id, sku_id=sku_id, units=1)

    page = viewmodels.movement_book(session)

    _assert_only_primitives(page)


def test_the_movement_book_names_the_origin_that_wrote_each_line(
    session: SnakeSession,
) -> None:
    """`receive` is the floor and `ship` is the shop, and the page says which without a join.

    A compound loads no relationships, so the warehouse code and the SKU name come from lookups —
    the same shape the reorder screen takes, and the assertion that breaks if somebody "simplifies"
    the page into hopping a relation the answer does not have.
    """
    warehouse_id = _warehouse(session, "BCN")
    sku_id = _sku(session, "Moved")
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=sku_id, units=5)
    usecases.ship(session, warehouse_id=warehouse_id, sku_id=sku_id, units=1)

    page = viewmodels.movement_book(session)
    origins = {line["reason"]: line["origin"] for line in page["lines"]}

    assert origins == {"purchase": "floor", "sale": "shop"}
    assert {line["warehouse_code"] for line in page["lines"]} == {"BCN"}
    assert {line["sku_name"] for line in page["lines"]} == {"Moved"}
    assert all("id" not in line for line in page["lines"]), (
        "a ledger line is a fact and not a row: there is no id to put on the page"
    )


def test_a_stockroom_that_has_moved_nothing_is_an_empty_book(
    session: SnakeSession,
) -> None:
    """Nothing having moved is an answer, so it cannot be a refusal."""
    _warehouse(session)

    page = viewmodels.movement_book(session)

    assert page["lines"] == [] and page["line_count"] == 0


def _queries_of_a_book_page(session: SnakeSession, shipments: int) -> int:
    """Builds the book over `shipments` movements and returns how many statements it took."""
    warehouse_id = _warehouse(session)
    sku_id = _sku(session, "Moved")
    usecases.receive(
        session, warehouse_id=warehouse_id, sku_id=sku_id, units=shipments + 1
    )
    for _ in range(shipments):
        usecases.ship(session, warehouse_id=warehouse_id, sku_id=sku_id, units=1)
    with capture_queries() as collector:
        page = viewmodels.movement_book(session)
    assert page["line_count"] > 0, "the budget was measured over an empty page"
    return collector.report().count


def test_the_book_costs_the_same_at_two_shipments_and_at_twenty(
    make_session: Callable[[], SnakeSession],
) -> None:
    """The N+1 net: the book's lines carry ids that a naive fix would resolve one at a time."""
    small, large = make_session(), make_session()
    try:
        assert _queries_of_a_book_page(small, 2) == _queries_of_a_book_page(large, 20)
    finally:
        small.close()
        large.close()


def test_the_book_is_four_statements_where_the_compound_cannot_be_emitted(
    session: SnakeSession,
) -> None:
    """And what that constant IS on SQLite: an origin, the other origin, and the two catalogues.

    THREE on the engines that take parentheses around a bounded branch, because there the two origins
    arrive as one compound. The page declares which path it took rather than papering over it, which
    is the same bargain `order_report` strikes.
    """
    assert session.dialect.supports_parenthesised_compound is False

    assert _queries_of_a_book_page(session, 4) == 4


def test_the_warehouse_sheet_is_made_of_primitives(session: SnakeSession) -> None:
    """The sheet walks a to-many over the composite key, and not one movement leaks out as a model."""
    warehouse_id = _warehouse(session)
    _stocked(session, warehouse_id, 3)

    page = viewmodels.warehouse_sheet(session, warehouse_id)

    assert not isinstance(page, Failure)
    _assert_only_primitives(page)


def test_the_sheet_carries_every_movement_of_every_line(session: SnakeSession) -> None:
    """One page, both halves of the question: what is held, and what each line has been doing.

    The pages could already answer the first half through the listing and the second half a pair at a
    time. What is asserted here is that the two arrive TOGETHER — and `net_delta` beside `on_hand`,
    because a line that received forty and shipped forty is busy and unchanged, and only one of those
    two numbers says so.
    """
    warehouse_id = _warehouse(session)
    quiet, busy = _sku(session, "Quiet"), _sku(session, "Busy")
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=quiet, units=7)
    usecases.receive(session, warehouse_id=warehouse_id, sku_id=busy, units=40)
    usecases.ship(session, warehouse_id=warehouse_id, sku_id=busy, units=40)

    page = viewmodels.warehouse_sheet(session, warehouse_id)

    assert not isinstance(page, Failure)
    assert page["warehouse"]["code"] == "MAD"
    assert page["line_count"] == 2 and page["movement_count"] == 3
    by_sku = {line["sku_id"]: line for line in page["lines"]}
    assert by_sku[quiet]["sku_name"] == "Quiet"
    assert by_sku[quiet]["movement_count"] == 1 and by_sku[quiet]["net_delta"] == 7
    assert by_sku[busy]["on_hand"] == 0 and by_sku[busy]["net_delta"] == 0
    assert [m["delta"] for m in by_sku[busy]["movements"]] == [40, -40]


def test_a_warehouse_that_does_not_exist_is_a_failure_and_not_an_empty_sheet(
    session: SnakeSession,
) -> None:
    """An empty shed and a shed that was never built are the same empty list otherwise."""
    result = viewmodels.warehouse_sheet(session, 9999)

    assert isinstance(result, Failure)
    assert result.reason == "not_found"


def _queries_of_a_warehouse_sheet(session: SnakeSession, lines: int) -> int:
    """Builds the sheet over `lines` stocked pairs and returns how many statements it took."""
    warehouse_id = _warehouse(session)
    _stocked(session, warehouse_id, lines)
    with capture_queries() as collector:
        page = viewmodels.warehouse_sheet(session, warehouse_id)
    assert not isinstance(page, Failure)
    assert page["line_count"] == lines, "the budget was measured over the wrong sheet"
    return collector.report().count


def test_the_sheet_costs_the_same_at_two_lines_and_at_twenty(
    make_session: Callable[[], SnakeSession],
) -> None:
    """THE POINT OF THE PAGE, asserted: the movements of every line arrive in ONE select-in.

    This is the to-many over a foreign key two columns wide, so the prefetch binds two placeholders
    per parent — the shape that is easiest to get wrong and would show up here as a slope rather than
    as a wrong answer. Reading the same thing from the pair detail costs one request per SKU, which
    is what the demos did before this page existed.
    """
    small, large = make_session(), make_session()
    try:
        assert _queries_of_a_warehouse_sheet(small, 2) == _queries_of_a_warehouse_sheet(
            large, 20
        )
    finally:
        small.close()
        large.close()


def test_the_warehouse_sheet_is_five_statements(session: SnakeSession) -> None:
    """And what that constant IS: the warehouse, the probe, the rows, the movements, the SKUs.

    The probe is `stock_with_movements` checking the warehouse exists after this page has just
    fetched it, and it is written down rather than shaved off: reaching past the use case to save one
    statement would put "what this page means" in a second place. The number is here so that the day
    it moves somebody has to say why.
    """
    assert _queries_of_a_warehouse_sheet(session, 5) == 5
