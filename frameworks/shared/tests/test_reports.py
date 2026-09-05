"""The two report pages: the figures a `filter` cannot produce, and what each of them costs.

A report is the page type the plan added to exercise the half of the ORM the demos never touched —
`annotate`, `group_by`, `having`, a window function and a compound. Every one of those is a query
shape rather than a query, and the way a shape gets lost is not that somebody deletes it: it is that
somebody answers the same question a cheaper-looking way and the page still shows the right numbers.
A `GROUP BY` + `HAVING` rewritten as a Python filter over every group produces identical output. A
window function rewritten as a lookup per row produces identical output. So the assertions here come
in pairs — what the page SAYS, and what the page COST — and the second half is the one that catches
the rewrite.

THE COSTS ARE LITERALS, which the phase's gate demands and which the sibling budget tests
deliberately avoid for listings. The difference is real: a listing's budget is asserted against
ITSELF at two sizes because what must not change there is the SLOPE, and a literal would turn every
legitimate rewrite red. A report has no slope to measure — every statement on it is an aggregate over
the whole table — so the only thing left to pin IS the number, and each one is accounted for in the
docstring beside it. A number nobody can account for is a number that grows.

ONE OF THOSE NUMBERS DEPENDS ON THE ENGINE, and it is written down twice rather than averaged. The
orders report's highlights are a `UNION` of two branches that each keep their own `LIMIT`, and a
branch keeps a `LIMIT` only inside parentheses: Postgres and MySQL answer `Cap.PARENTHESISED_COMPOUND`
with `Full`, SQLite with `Nope`. So the page is five statements on two engines and six on the third,
and both are asserted — the six against the SQLite the suite runs on, the five against the SQL that
Postgres would be handed, emitted without a server because emitting needs none.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from snakeorm import PostgresDialect, SnakeModel, SnakeSession
from snakeorm.debug import capture_queries

from shared.dto.inventory_dto import (
    busy_sku_dict,
    moved_sku_dict,
    movement_trail_dict,
    ranked_stock_dict,
    stock_report_dict,
    warehouse_stats_dict,
)
from shared.models import OrderState, SkuKind, User
from shared.selectors import orders_selectors
from shared.usecases import inventory_usecases as inventory
from shared.usecases import orders_usecases as orders
from shared.usecases.result import Failure
from shared.viewmodels import inventory_viewmodels, orders_viewmodels

# What a template is allowed to receive. `bool` is listed for the reader even though it is an `int`.
_PRIMITIVES = (str, int, bool, type(None))


def _leaves(value: object) -> Iterator[object]:
    """Every leaf of a page dict, walking through the dicts and lists it nests."""
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


def _warehouse(session: SnakeSession, code: str) -> int:
    """One warehouse through the use case, never a raw insert."""
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


def _stock(session: SnakeSession, warehouse_id: int, sku_id: int, units: int) -> None:
    """A stock level set by a physical count: an upsert, no movement written."""
    counted = inventory.count_stock(
        session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=units
    )
    assert not isinstance(counted, Failure), counted


def _move(session: SnakeSession, warehouse_id: int, sku_id: int, times: int) -> None:
    """`times` real receipts, so the movements exist the way a demo would have made them."""
    for _ in range(times):
        received = inventory.receive(
            session, warehouse_id=warehouse_id, sku_id=sku_id, units=1
        )
        assert not isinstance(received, Failure), received


def _customer(session: SnakeSession, username: str) -> int:
    """A user, added directly: no domain in this repository has a use case that creates one."""
    user = session.add(
        User(username=username, email=f"{username}@demo.dev", password_hash="x")
    )
    session.commit()
    return user.id


def _place(
    session: SnakeSession,
    *,
    reference: str,
    customer_id: int,
    warehouse_id: int,
    sku_id: int,
    units: int = 1,
) -> int:
    """One DRAFT order of one line, through the use case. Returns its id."""
    order = orders.place_order(
        session,
        reference=reference,
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        lines=[(sku_id, units)],
    )
    assert not isinstance(order, Failure), order
    return order.id


# ---- The inventory report ------------------------------------------------------------------------


def _stocked_warehouse(session: SnakeSession) -> tuple[int, list[int]]:
    """One warehouse, three SKUs, and movements on two of them. The report's whole fixture.

    The third SKU is stocked and NEVER moved on purpose: it is the row the `DISTINCT` over the join
    has to leave out and the one `never_moved` has to count. A fixture where everything moves cannot
    tell a correct fold from a `SELECT` that forgot the `DISTINCT`.
    """
    warehouse_id = _warehouse(session, "MAD")
    skus = [_sku(session, name) for name in ("Alpha", "Beta", "Gamma")]
    _stock(session, warehouse_id, skus[0], 100)
    _stock(session, warehouse_id, skus[1], 40)
    _stock(session, warehouse_id, skus[2], 40)
    _move(session, warehouse_id, skus[0], 4)
    _move(session, warehouse_id, skus[1], 1)
    return warehouse_id, skus


def test_the_inventory_report_is_made_of_primitives(session: SnakeSession) -> None:
    """The report hands the template strings and numbers, never a `Warehouse` nor a `Decimal`."""
    _stocked_warehouse(session)

    _assert_only_primitives(inventory_viewmodels.stock_report(session))


def test_the_warehouse_figures_come_from_annotate_already_flattened(
    session: SnakeSession,
) -> None:
    """`annotate` puts two aggregates on the warehouse row, and the page carries them as numbers.

    A template summing `warehouse.stock` itself would be running an aggregate in the renderer, one
    query per warehouse, in the layer no `assert_queries` watches.
    """
    _stocked_warehouse(session)

    page = inventory_viewmodels.stock_report(session)

    assert [row["code"] for row in page["warehouses"]] == ["MAD"]
    assert page["warehouses"][0]["sku_count"] == 3
    assert page["warehouses"][0]["total_units"] == 100 + 4 + 40 + 1 + 40


def test_having_keeps_only_the_skus_that_move_often_enough(
    session: SnakeSession,
) -> None:
    """The aggregate filtered by its OWN aggregate: a threshold no `WHERE` could apply.

    Alpha moved four times and Beta once; at a threshold of two only Alpha survives. What makes this
    a `HAVING` and not a `filter` is that "how many times it moved" does not exist until the rows are
    grouped, so there is nothing for a row-by-row condition to look at.
    """
    _stocked_warehouse(session)

    page = inventory_viewmodels.stock_report(session, minimum_moves=2)

    assert [row["sku_name"] for row in page["busy_skus"]] == ["Alpha"]
    assert page["busy_skus"][0]["moves"] == 4
    assert page["busy_skus"][0]["net_delta"] == 4
    assert page["minimum_moves"] == 2


def test_lowering_the_threshold_lets_the_quieter_sku_back_in(
    session: SnakeSession,
) -> None:
    """The threshold is a parameter and it really reaches the SQL, rather than being decoration.

    A `HAVING` hard-wired in the selector would give the same answer at the default and the same
    answer here, which is exactly how a filter stops being a filter without anybody noticing.
    """
    _stocked_warehouse(session)

    page = inventory_viewmodels.stock_report(session, minimum_moves=1)

    assert [row["sku_name"] for row in page["busy_skus"]] == ["Alpha", "Beta"]


def test_the_window_ranks_inside_the_warehouse_and_shares_a_tie(
    session: SnakeSession,
) -> None:
    """`RANK() OVER (PARTITION BY ...)` gives every row a fact about its NEIGHBOURS, uncollapsed.

    This fixture is built to contain a TIE, which no other test in the file has: two SKUs holding
    fifty units each. They must SHARE the second position, because `rank()` was chosen over
    `row_number()` precisely so that a genuine tie is not broken by an id the data never asked to be
    ordered by. With `row_number()` this would read 1, 2, 3 and nobody would be able to tell from the
    page that the second and third shelves hold the same amount.
    """
    warehouse_id = _warehouse(session, "MAD")
    first, second, third = (_sku(session, name) for name in ("Alpha", "Beta", "Gamma"))
    _stock(session, warehouse_id, first, 100)
    _stock(session, warehouse_id, second, 50)
    _stock(session, warehouse_id, third, 50)

    page = inventory_viewmodels.stock_report(session)
    positions = [(row["sku_name"], row["position"]) for row in page["ranking"]]

    assert positions == [("Alpha", 1), ("Beta", 2), ("Gamma", 2)]


def test_the_window_restarts_at_one_in_every_warehouse(session: SnakeSession) -> None:
    """The PARTITION is what makes it a window and not an ordering: each warehouse ranks its own.

    Without the partition the second warehouse's best SKU would be ranked against the first
    warehouse's, and the page would say a full shelf in Barcelona is the fourth-best shelf in Madrid.
    """
    madrid = _warehouse(session, "MAD")
    barcelona = _warehouse(session, "BCN")
    sku = _sku(session, "Alpha")
    other = _sku(session, "Beta")
    _stock(session, madrid, sku, 100)
    _stock(session, madrid, other, 10)
    _stock(session, barcelona, sku, 5)

    page = inventory_viewmodels.stock_report(session)
    by_warehouse: dict[str, list[int]] = {}
    for row in page["ranking"]:
        by_warehouse.setdefault(row["warehouse_code"], []).append(row["position"])

    assert by_warehouse == {"MAD": [1, 2], "BCN": [1]}


def test_distinct_folds_the_join_back_and_the_ratio_says_what_never_moved(
    session: SnakeSession,
) -> None:
    """The JOIN multiplies a SKU by its movements; `DISTINCT` folds it back to the set that moved.

    Alpha has four movements. Without the fold it would appear four times and `moved_count` would say
    five out of three SKUs, which is not a rounding error but a different question answered by
    accident. `never_moved` is the figure the page is really about, and it is one subtraction done
    here rather than two ways in two templates.
    """
    _stocked_warehouse(session)

    page = inventory_viewmodels.stock_report(session)

    assert [row["sku_name"] for row in page["moved_skus"]] == ["Alpha", "Beta"]
    assert page["moved_count"] == 2
    assert page["total_skus"] == 3
    assert page["never_moved"] == 1


def test_the_running_total_and_the_moving_one_are_different_answers(
    session: SnakeSession,
) -> None:
    """FOUR receipts of one unit: the running total is 1,2,3,4 and the three-deep one is 1,2,3,3.

    THEY DIVERGE ON THE FOURTH ROW and nowhere before it, which is the whole reason the fixture makes
    four movements and not three. `over(order_by=...)` alone gives the accumulated figure — the
    default frame runs from the start of the partition to the current row — and that is ONE useful
    answer. "How much has moved lately" is a different one, and until the frame existed it could not
    be asked at all: the rows had to come to Python and be added up there.

    A test that only checked the trailing column would pass with the frame silently dropped, because
    the first three rows agree. The pair is asserted together for that reason.
    """
    warehouse_id, skus = _stocked_warehouse(session)

    page = inventory_viewmodels.stock_report(session)
    trail = [row for row in page["trail"] if row["sku"] == "Alpha"]

    assert [row["running"] for row in trail] == [1, 2, 3, 4]
    assert [row["moving"] for row in trail] == [1, 2, 3, 3]


def test_the_moving_total_restarts_in_every_pair(session: SnakeSession) -> None:
    """The frame is measured INSIDE a partition: a different SKU is a different series.

    Without the `PARTITION BY`, Beta's single movement would carry Alpha's tail into it and read 4
    instead of 1 — a number that is not wrong so much as about the wrong thing.
    """
    _stocked_warehouse(session)

    page = inventory_viewmodels.stock_report(session)
    beta = [row for row in page["trail"] if row["sku"] == "Beta"]

    assert [row["moving"] for row in beta] == [1]


def test_the_inventory_report_payload_carries_every_figure(
    session: SnakeSession,
) -> None:
    """The JSON surface of the report names all SIX fields, and the keys are read off the dataclass.

    Written against `dataclasses.fields` and not against a list of six strings, because a literal
    list is the thing that stays right while the report grows: a seventh figure added to
    `StockReport` would have to be added to the assertion as well, by the same person who forgot to
    add it to the serialiser. Asking the dataclass means the day the report grows, this fails.

    That failure has already happened once in this package, on the orders report — `baskets` was
    fetched, paid for and dropped one layer above the query — and it went unseen because every other
    net was looking somewhere else: the budget still counted the statement, the routes still existed
    on all three demos, and the page still drew the table. `shared/dto/` is where the two
    presentations part company, so it is the only place the count can be made.

    Each key is then held against the ROW serialiser it is supposed to go through, which is the half
    the key count cannot see: `ranking` carrying `busy_skus`' shape would have six right keys and the
    wrong document under three of them. The values come last, pinned against the same fixture the
    HTML assertions above use, and they are asserted on the TYPED side — a tuple out of `StockReport`
    handed to one serialiser — so nothing in this file has to index its way through a payload and
    pick up an `Any` doing it.
    """
    _stocked_warehouse(session)
    report = inventory.stock_report(session, minimum_moves=2)

    document = stock_report_dict(report)

    assert set(document) == {
        field.name for field in dataclasses.fields(inventory.StockReport)
    }
    assert document["warehouses"] == [
        warehouse_stats_dict(row) for row in report.warehouses
    ]
    assert document["busy_skus"] == [busy_sku_dict(row) for row in report.busy_skus]
    assert document["ranking"] == [ranked_stock_dict(row) for row in report.ranking]
    assert document["moved_skus"] == [moved_sku_dict(row) for row in report.moved_skus]
    assert document["total_skus"] == report.total_skus == 3
    assert document["trail"] == [movement_trail_dict(row) for row in report.trail]

    assert busy_sku_dict(report.busy_skus[0]) == {
        "sku_name": "Alpha",
        "moves": 4,
        "net_delta": 4,
    }
    assert [ranked_stock_dict(row)["position"] for row in report.ranking] == [1, 2, 3]
    assert {moved_sku_dict(row)["sku_name"] for row in report.moved_skus} == {
        "Alpha",
        "Beta",
    }


def test_the_inventory_report_is_six_statements(session: SnakeSession) -> None:
    """SIX, as a literal, and every one of them accounted for.

    The `annotate` over the warehouses, the `GROUP BY` + `HAVING` over the movements, the window over
    the stock, the JOIN folded with `DISTINCT`, the `COUNT` of SKUs that turns the fold into a ratio,
    and the movement trail.

    THE SIXTH IS THE ONE THAT HAD TO BE ARGUED FOR, which is exactly what the previous version of
    this docstring demanded of it. It earns its place by carrying TWO windows rather than one: the
    running total of each pair and the total over its last three movements, computed side by side in
    a single statement. Asking them apart would be two passes over the same rows, and computing the
    moving one in Python would mean bringing every movement across the wire to add up five numbers.
    """
    _stocked_warehouse(session)

    with capture_queries() as collector:
        inventory_viewmodels.stock_report(session)

    assert collector.report().count == 6, collector.report().to_text()


def test_the_inventory_report_costs_the_same_at_three_skus_and_at_thirty(
    make_session: Callable[[], SnakeSession],
) -> None:
    """And it is flat: every statement on it is an aggregate over the whole table.

    Two databases and not two calls on one, because the second measurement has to start from a clean
    slate. This is the pair the literal above cannot prove on its own — a page can cost five
    statements at three rows and five hundred at thirty.
    """

    def cost(session: SnakeSession, skus: int) -> int:
        warehouse_id = _warehouse(session, "MAD")
        for index in range(skus):
            sku_id = _sku(session, f"Sku {index:02d}")
            _stock(session, warehouse_id, sku_id, 10)
            _move(session, warehouse_id, sku_id, 2)
        with capture_queries() as collector:
            inventory_viewmodels.stock_report(session)
        return collector.report().count

    small, large = make_session(), make_session()
    try:
        assert cost(small, 3) == cost(large, 30)
    finally:
        small.close()
        large.close()


# ---- The orders report ---------------------------------------------------------------------------


def _shop_with_orders(session: SnakeSession) -> None:
    """Two customers, one of them a repeat buyer, so every figure on the report has two cases.

    Ana orders three times and Ben once. That asymmetry is what the `HAVING` filters on, what the
    window numbers, and what makes the highlights worth deduplicating — with one order each, "the
    biggest" and "the newest" are the same list and the `UNION` would prove nothing.
    """
    warehouse_id = _warehouse(session, "MAD")
    sku_id = _sku(session, "Alpha")
    _stock(session, warehouse_id, sku_id, 1000)
    ana = _customer(session, "ana")
    ben = _customer(session, "ben")
    for index, units in enumerate((1, 5, 2)):
        _place(
            session,
            reference=f"ORD-A{index}",
            customer_id=ana,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            units=units,
        )
    _place(
        session,
        reference="ORD-B0",
        customer_id=ben,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        units=9,
    )


def test_the_orders_report_is_made_of_primitives(session: SnakeSession) -> None:
    """The report hands the template strings and numbers, never an `Order` nor a `Decimal`."""
    _shop_with_orders(session)

    _assert_only_primitives(orders_viewmodels.order_report(session))


def test_annotate_lists_every_customer_including_the_one_who_never_ordered(
    session: SnakeSession,
) -> None:
    """`annotate` keeps the customer with zero orders, which a `GROUP BY` over the orders would drop.

    That row is not noise: "signed up and never bought" is the question the roll call exists to
    answer, and it is exactly the row the grouped query underneath cannot produce.
    """
    _shop_with_orders(session)
    _customer(session, "cleo")

    page = orders_viewmodels.order_report(session)
    counts = {row["username"]: row["order_count"] for row in page["customers"]}

    assert counts == {"ana": 3, "ben": 1, "cleo": 0}
    assert [row for row in page["customers"] if row["username"] == "cleo"][0][
        "ordered_total"
    ] == "0.00"


def test_having_keeps_only_the_customers_who_came_back(session: SnakeSession) -> None:
    """The aggregate filtered by its own aggregate, on the money side of the graph.

    Ana ordered three times and Ben once, so at a threshold of two only Ana survives — and Ana's
    money comes along, formatted, without being what the filter looked at. The threshold is on the
    COUNT and not on the SUM deliberately: `Order.total` is text on SQLite, where a `HAVING` over a
    summed `Decimal` is not merely different but silently empty.
    """
    _shop_with_orders(session)

    page = orders_viewmodels.order_report(session, minimum_orders=2)

    assert [row["username"] for row in page["repeat_customers"]] == ["ana"]
    assert page["repeat_customers"][0]["order_count"] == 3
    assert page["minimum_orders"] == 2


def test_the_states_table_groups_by_a_value_and_not_by_a_table(
    session: SnakeSession,
) -> None:
    """A plain `GROUP BY` over an enum column: four orders, all of them still drafts.

    It comes back as tuples and not as a `@snake_result` because there is no `states` table to be the
    row, and the view model is where the enum's value gets a label a person can read.
    """
    _shop_with_orders(session)

    page = orders_viewmodels.order_report(session)
    drafts = [row for row in page["states"] if row["state"] == OrderState.DRAFT.value]

    assert drafts[0]["order_count"] == 4
    assert drafts[0]["state_label"] == "Draft"


def test_the_window_numbers_each_order_within_its_own_customer(
    session: SnakeSession,
) -> None:
    """`ROW_NUMBER() OVER (PARTITION BY customer_id ...)` says which of Ana's orders each one is.

    Ana's three orders are numbered one, two and three in the order she placed them, and Ben's single
    order is a one — not a four. That restart is the partition, and it is the whole difference between
    a window and an ordering: a `1` means a first-time buyer on a page that is also showing a `3`.
    """
    _shop_with_orders(session)

    page = orders_viewmodels.order_report(session)
    numbered = {row["reference"]: row["nth_for_customer"] for row in page["sequence"]}

    assert numbered == {"ORD-A0": 1, "ORD-A1": 2, "ORD-A2": 3, "ORD-B0": 1}


def test_the_highlights_stack_two_bounded_questions_into_one_list(
    session: SnakeSession,
) -> None:
    """The `UNION`: the biggest orders and the newest ones, deduplicated into one list.

    Bounded at two so the two questions genuinely disagree — Ben's nine units are the biggest and
    Ana's last order is the newest — and an order that answers both appears ONCE, which is what
    `UNION` buys over `UNION ALL` and over two lists side by side.
    """
    _shop_with_orders(session)

    page = orders_viewmodels.order_report(session, highlight_size=2)
    references = [row["reference"] for row in page["highlights"]]

    assert len(references) == len(set(references)), f"duplicated: {references}"
    assert "ORD-B0" in references, "the biggest order is missing from the highlights"
    assert "ORD-A2" in references, "the newest order is missing from the highlights"


def test_the_highlight_row_carries_no_relation_because_a_compound_loads_none(
    session: SnakeSession,
) -> None:
    """The thin shape is the ORM's answer, written into the page rather than worked around.

    A compound loads NO relationships — an `include` on a branch is refused when it is built — so a
    highlight knows its own columns and nothing else. Reaching for `order.customer` here would be a
    query per highlight; the shape says so by having no place to put one.
    """
    _shop_with_orders(session)

    page = orders_viewmodels.order_report(session, highlight_size=2)

    assert page["highlights"]
    for row in page["highlights"]:
        assert set(row) == {
            "id",
            "reference",
            "state",
            "state_label",
            "total",
            "placed_at",
        }


def test_the_page_says_whether_the_union_ran_as_one_statement(
    session: SnakeSession,
) -> None:
    """The one figure on the report that depends on the ENGINE rather than on the data.

    SQLite answers `Cap.PARENTHESISED_COMPOUND` with `Nope`, so the fixture's session says `False`
    and the page took the two-statement fold. A demo that hid that would be hiding the most
    interesting thing on the page.
    """
    _shop_with_orders(session)

    page = orders_viewmodels.order_report(session)

    assert page["union_supported"] is False
    assert session.dialect.supports_parenthesised_compound is False


def test_the_skus_of_an_order_arrive_joined_in_one_cell(session: SnakeSession) -> None:
    """Three SKUs on one order, in ONE string, from ONE statement.

    THIS IS THE READ THAT USED TO GO BACK TO PYTHON. A listing that wants "what is on this order"
    beside each row had two options before `string_agg`: a second query plus a grouping pass, or
    walking `order.lines` in the template — which is the N+1 wearing the clothes of an attribute
    access. Neither is what the database was for.

    Inserted GAMMA, ALPHA, BETA and asserted alphabetically, because the `order_by` INSIDE the
    aggregate is the half that is easy to leave out and impossible to notice: without it the engine
    concatenates in whatever order it read the rows, and the same page can say `Gamma, Alpha, Beta`
    on one run and something else on the next.
    """
    warehouse_id = _warehouse(session, "MAD")
    skus = {name: _sku(session, name) for name in ("Gamma", "Alpha", "Beta")}
    for sku_id in skus.values():
        _stock(session, warehouse_id, sku_id, 100)
    customer_id = _customer(session, "ana")
    placed = orders.place_order(
        session,
        reference="ORD-MULTI",
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        lines=[(skus["Gamma"], 1), (skus["Alpha"], 2), (skus["Beta"], 3)],
    )
    assert not isinstance(placed, Failure), placed

    page = orders_viewmodels.order_report(session)
    basket = [row for row in page["baskets"] if row["reference"] == "ORD-MULTI"]

    assert basket == [
        {"reference": "ORD-MULTI", "lines": 3, "skus": "Alpha, Beta, Gamma"}
    ]


def test_the_orders_report_is_seven_statements_on_sqlite(session: SnakeSession) -> None:
    """SEVEN here, and only one of them is the engine's rather than the page's.

    The `annotate` over the customers, the `GROUP BY` + `HAVING`, the states, the window strip and
    the baskets — five — and then the highlights, which are ONE `UNION` where a branch may keep its
    own `LIMIT` and TWO statements folded in Python where it may not. SQLite may not. The test below
    pins the other side.

    THE BASKETS ARE THE ONE THAT WAS ADDED, and they are one statement for a figure that reads like
    several: every order with its line count AND the names of its SKUs folded into a single cell.
    Before `string_agg` that cell cost a second query and a grouping pass, or a walk over
    `order.lines` in the template — the N+1 that does not look like one.
    """
    _shop_with_orders(session)

    with capture_queries() as collector:
        orders_viewmodels.order_report(session)

    assert collector.report().count == 7, collector.report().to_text()


def test_the_highlights_are_one_statement_where_the_engine_takes_parentheses() -> None:
    """FIVE on Postgres, proven by emitting the SQL rather than by running it.

    Building SQL executes nothing, so the engine that would run this does not have to be there — the
    colourless seam the whole ORM is built on is what makes this test possible without a server. What
    it pins is the thing the fold in `order_highlights` exists to replace: ONE statement, two
    branches, and a `LIMIT` inside each pair of parentheses rather than one bound belonging to the
    whole set.
    """
    biggest, newest = orders_selectors.highlight_branches(2)
    sql, params = biggest.union(newest).to_sql(PostgresDialect())

    assert sql.count("UNION") == 1
    assert sql.count("SELECT") == 2
    assert sql.startswith("(SELECT"), sql
    assert sql.count("LIMIT") == 2, (
        f"a branch lost its own bound and the LIMIT now belongs to the whole set: {sql}"
    )
    assert params == (2, 2)


def test_the_orders_report_costs_the_same_at_four_orders_and_at_forty(
    make_session: Callable[[], SnakeSession],
) -> None:
    """Flat: every statement on the report is an aggregate or carries its own `LIMIT`."""

    def cost(session: SnakeSession, placed: int) -> int:
        warehouse_id = _warehouse(session, "MAD")
        sku_id = _sku(session, "Alpha")
        _stock(session, warehouse_id, sku_id, 10_000)
        customer_id = _customer(session, "ana")
        for index in range(placed):
            _place(
                session,
                reference=f"ORD-{index:03d}",
                customer_id=customer_id,
                warehouse_id=warehouse_id,
                sku_id=sku_id,
            )
        with capture_queries() as collector:
            orders_viewmodels.order_report(session)
        return collector.report().count

    small, large = make_session(), make_session()
    try:
        assert cost(small, 4) == cost(large, 40)
    finally:
        small.close()
        large.close()


# ---- The compound on a real engine ----------------------------------------------------------------


def test_the_union_runs_on_a_real_postgres_and_deduplicates(
    postgres_pair: tuple[SnakeSession, SnakeSession],
) -> None:
    """The one test in this file that needs a server, because it is the one thing SQLite cannot show.

    The whole compound path — parenthesised branches, a `LIMIT` inside each, and the deduplication
    that makes it a `UNION` rather than two lists — only ever executes on Postgres and MySQL. The
    suite runs on SQLite, where `order_highlights` takes the fold instead, so without this test the
    branch that runs in every demo would be the branch nothing ever ran.

    Four orders, bounded at two: the biggest and the newest are different orders, so the union has
    something to merge, and the assertion is that it merged rather than concatenated.
    """
    session, _ = postgres_pair
    assert session.dialect.supports_parenthesised_compound is True
    _shop_with_orders(session)

    highlights = orders_selectors.order_highlights(session, size=2)
    references = [order.reference for order in highlights]

    assert len(references) == len(set(references)), f"duplicated: {references}"
    assert "ORD-B0" in references
    assert "ORD-A2" in references
    assert len(references) <= 4
