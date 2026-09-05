"""The view models of `orders`: flat pages, rules that match the domain, and a fixed query budget.

The sibling file `test_viewmodels.py` pins the same three things for the pilot domain, and everything
it says applies here. What this domain adds is a fourth, and it is the one worth reading.

`orders` is the only domain whose pages offer OPERATIONS — reserve, settle, cancel — and those three
are the ones that declare an isolation level as their first statement. So the page and the operation
are not two halves of one function here: a view model that read anything on the way to invoking one
of them spends the one moment the operation needed. The last two tests in this file provoke that on a
real Postgres, and they are two because the failure has two shapes: on a stock server it is SILENT and
the operation merely stops declaring its isolation level, and on a server configured any other way it
is `ActiveSqlTransaction`. A rule whose failure is invisible where it is written is a rule that needs
an executable witness rather than a warning nobody re-reads.

The `can_*` booleans get their own section, and they are checked against the OPERATIONS rather than
against a table of expected values. A table would pass the day somebody changes `reserve` and forgets
this file; asking the operation what it actually does, in every one of the five states, cannot.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from snakeorm import SnakeIsolation, SnakeModel, SnakeSession
from snakeorm.debug import capture_queries

from shared.models import OrderState, Plan, SkuKind, User
from shared.usecases import billing_usecases as billing
from shared.usecases import inventory_usecases as inventory
from shared.usecases import orders_usecases as usecases
from shared.usecases.result import Failure
from shared.viewmodels import orders_viewmodels as viewmodels

# What a template is allowed to receive. `bool` is listed for the reader even though it is an `int`.
_PRIMITIVES = (str, int, bool, type(None))


def _leaves(value: object) -> Iterator[object]:
    """Every leaf of a page dict, walking through the dicts and lists it nests.

    It has to recurse: an order page carries a list of lines, and a `Decimal` unit price two levels
    down is exactly the one that would reach the template unnoticed.
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


@dataclass(frozen=True, slots=True)
class Shop:
    """A customer with a subscription, a warehouse and one stocked SKU: the least an order needs.

    It is one dataclass and not four fixtures because every test here starts from the same five rows,
    and the interesting differences are what happens AFTERWARDS — which state the order reaches, how
    many units are on the shelf. A frozen record of ids keeps that difference visible in the test.
    """

    customer_id: int
    subscription_id: int
    warehouse_id: int
    sku_id: int


def _shop(session: SnakeSession, *, on_hand: int = 1000) -> Shop:
    """Builds the five rows through the USE CASES of each domain, never with raw inserts.

    The two exceptions are the `User` and the `Plan`, which have no creating use case in this
    repository at all — the same two `test_orders_concurrency.py` adds by hand, for the same reason.
    Everything that HAS a use case goes through it, so this setup cannot drift from the rows a demo
    would really write.
    """
    customer = session.add(
        User(username="buyer", email="buyer@demo.dev", password_hash="x")
    )
    plan = session.add(Plan(name="plan-basic", price_cents=900))
    session.commit()
    subscription = billing.subscribe(session, customer.id, plan.id)

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
    counted = inventory.count_stock(
        session, warehouse_id=warehouse.id, sku_id=sku.id, on_hand=on_hand
    )
    assert not isinstance(counted, Failure), counted
    return Shop(
        customer_id=customer.id,
        subscription_id=subscription.id,
        warehouse_id=warehouse.id,
        sku_id=sku.id,
    )


def _place(
    session: SnakeSession, shop: Shop, reference: str, *, wanted: int = 1
) -> int:
    """One DRAFT order for `wanted` units of the shop's SKU. Returns its id."""
    order = usecases.place_order(
        session,
        reference=reference,
        customer_id=shop.customer_id,
        warehouse_id=shop.warehouse_id,
        lines=[(shop.sku_id, wanted)],
    )
    assert not isinstance(order, Failure), order
    return order.id


def _order_in(
    session: SnakeSession, shop: Shop, state: OrderState, reference: str
) -> int:
    """An order that has REACHED `state`, moved there by the operations rather than by an UPDATE.

    Writing the column directly would be quicker and would prove nothing: the point of checking the
    `can_*` rules in every state is that the states were arrived at the way a demo arrives at them.
    """
    order_id = _place(session, shop, reference)
    if state is OrderState.DRAFT:
        return order_id
    if state is OrderState.CANCELLED:
        assert not isinstance(
            usecases.cancel_order(session, order_id=order_id), Failure
        )
        return order_id
    if state is OrderState.INVOICED:
        invoice = billing.issue_invoice(session, shop.subscription_id, 1000)
        assert not isinstance(
            usecases.attach_invoice(session, order_id=order_id, invoice_id=invoice.id),
            Failure,
        )
        return order_id
    assert not isinstance(usecases.reserve(session, order_id=order_id), Failure)
    if state is OrderState.RESERVED:
        return order_id
    assert not isinstance(
        usecases.settle(
            session, order_id=order_id, subscription_id=shop.subscription_id
        ),
        Failure,
    )
    return order_id


def _row(session: SnakeSession, order_id: int) -> viewmodels.OrderRow:
    """The order's row as the pages carry it. Same shape on every page, so any of them will do."""
    page = viewmodels.order_detail(session, order_id)
    assert not isinstance(page, Failure), page
    return page["order"]


# ---- Only primitives come out ------------------------------------------------------------------


def test_the_list_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The listing hands the template strings and numbers, never an `Order` nor its customer."""
    shop = _shop(session)
    _place(session, shop, "ORD-1")

    page = viewmodels.order_list(session)

    _assert_only_primitives(page)


def test_the_detail_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The detail navigates three to-one relations and a to-many, and none of the four leaks out."""
    shop = _shop(session)
    order_id = _order_in(session, shop, OrderState.INVOICED, "ORD-1")

    page = viewmodels.order_detail(session, order_id)

    assert not isinstance(page, Failure)
    _assert_only_primitives(page)


def test_the_form_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The form's options carry a price and a customer, both `Decimal` and model until formatted."""
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1")

    page = viewmodels.order_form(session, order_id)

    assert not isinstance(page, Failure)
    _assert_only_primitives(page)


def test_the_delete_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The confirmation names the lines that would be orphaned, and a line carries money."""
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1")

    page = viewmodels.order_delete_confirm(session, order_id)

    assert not isinstance(page, Failure)
    _assert_only_primitives(page)


def test_the_operation_page_is_made_of_primitives(session: SnakeSession) -> None:
    """The operation page reads across three domains — order, stock, subscription — and flattens all."""
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1")

    page = viewmodels.order_operation(session, order_id)

    assert not isinstance(page, Failure)
    _assert_only_primitives(page)


# ---- The relation navigation the template no longer does ---------------------------------------


def test_the_row_carries_the_customer_and_the_warehouse_already_flattened(
    session: SnakeSession,
) -> None:
    """`customer` and `warehouse` come from two to-one hops made HERE, not in the HTML."""
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1")

    row = _row(session, order_id)

    assert row["customer"] == "buyer"
    assert row["customer_id"] == shop.customer_id
    assert row["warehouse"] == "MAD"
    assert row["warehouse_id"] == shop.warehouse_id
    assert row["reference"] == "ORD-1"
    assert row["placed_at"].startswith("20")


def test_money_is_formatted_here_and_not_in_the_template(
    session: SnakeSession,
) -> None:
    """Money leaves this layer as text with its two decimals, because a template cannot round.

    Three different sources have to agree on that: the order's stored total, the line's unit price
    copied off the SKU, and the invoice's amount, which `billing` keeps in integer CENTS. The third
    is the one worth pinning — a cents-to-money conversion written in a template is written twice.
    """
    shop = _shop(session)
    order_id = _order_in(session, shop, OrderState.INVOICED, "ORD-1")

    page = viewmodels.order_detail(session, order_id)

    assert not isinstance(page, Failure)
    assert page["order"]["total"] == "10.00"
    assert page["lines"][0]["unit_price"] == "10.00"
    assert page["lines"][0]["line_total"] == "10.00"
    assert page["invoice"] is not None
    assert page["invoice"]["amount"] == "10.00"


def test_the_state_carries_a_label_the_template_does_not_invent(
    session: SnakeSession,
) -> None:
    """`state` is the value a form posts back; `state_label` is what a person reads. Both travel.

    Only one of the two would force the other to be derived somewhere, and the only somewhere left
    is the template — where two demos would each capitalise it their own way.
    """
    shop = _shop(session)
    order_id = _order_in(session, shop, OrderState.RESERVED, "ORD-1")

    row = _row(session, order_id)

    assert (row["state"], row["state_label"]) == ("reserved", "Reserved")


def test_every_state_of_the_domain_has_a_label() -> None:
    """A sixth state added tomorrow must fail HERE, not paint a `KeyError` into a page.

    The label table is written out by hand so a label can differ from the enum's value. What that
    buys is also what it costs: a table can fall behind the enum, and nothing else would say so.
    """
    for state in OrderState:
        assert viewmodels.state_label(state).strip(), state


# ---- The `can_*` rules, checked against the operations themselves -------------------------------


def _rule_matches_the_operation(
    session: SnakeSession,
    shop: Shop,
    state: OrderState,
    tag: str,
    key: str,
    run: Callable[[int], object],
) -> None:
    """Builds an order in `state`, reads its boolean, runs the operation and compares the two.

    Comparing against the OPERATION and not against an expected value is the whole point. A table of
    expectations is a second copy of the domain's rules, and a second copy is what goes stale the day
    `reserve` changes and nobody remembers this file exists.
    """
    order_id = _order_in(session, shop, state, f"{tag}-{state.value}")
    allowed = _row(session, order_id)[key]  # type: ignore[literal-required]

    outcome = run(order_id)

    assert allowed == (not isinstance(outcome, Failure)), (
        f"{key} says {allowed} in {state.value} but the operation answered {outcome!r}"
    )


def test_can_reserve_matches_what_reserve_does_in_every_state(
    session: SnakeSession,
) -> None:
    """A draft can be reserved and nothing else can, and the button agrees with the operation."""
    shop = _shop(session)
    for state in OrderState:
        _rule_matches_the_operation(
            session,
            shop,
            state,
            "RSV",
            "can_reserve",
            lambda order_id: usecases.reserve(session, order_id=order_id),
        )


def test_can_settle_matches_what_settle_does_in_every_state(
    session: SnakeSession,
) -> None:
    """Only a RESERVED order can be settled: the units are held, the money has not moved yet."""
    shop = _shop(session)
    for state in OrderState:
        _rule_matches_the_operation(
            session,
            shop,
            state,
            "STL",
            "can_settle",
            lambda order_id: usecases.settle(
                session, order_id=order_id, subscription_id=shop.subscription_id
            ),
        )


def test_can_cancel_matches_what_cancel_does_in_every_state(
    session: SnakeSession,
) -> None:
    """Cancelling is offered from the two OPEN states, and refused once anything has been billed.

    That is the rule a template would otherwise spell out as `state == "draft" or state ==
    "reserved"` — the domain's rule, copied into the presentation layer, twice, once per demo.
    """
    shop = _shop(session)
    for state in OrderState:
        _rule_matches_the_operation(
            session,
            shop,
            state,
            "CNL",
            "can_cancel",
            lambda order_id: usecases.cancel_order(session, order_id=order_id),
        )


def test_a_draft_with_no_lines_is_not_offered_a_reservation(
    session: SnakeSession,
) -> None:
    """`reserve` refuses an empty order, and the operation page says so instead of offering a button.

    An empty draft is reachable: `place_order` refuses to create one, and `remove_line` empties one.
    The listing cannot see it — it does not count lines — so this rule lives on the page that does.
    """
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1")
    assert usecases.remove_line(session, order_id=order_id, sku_id=shop.sku_id) is None

    page = viewmodels.order_operation(session, order_id)

    assert not isinstance(page, Failure)
    assert page["can_reserve"] is False
    assert page["reserve_blocked"]
    assert usecases.reserve(session, order_id=order_id) == Failure("conflict")


# ---- Pagination ---------------------------------------------------------------------------------


def test_the_middle_page_has_a_previous_and_a_next(session: SnakeSession) -> None:
    """Seven orders at three per page is three pages, and the second one is surrounded."""
    shop = _shop(session)
    for index in range(7):
        _place(session, shop, f"ORD-{index}")

    page = viewmodels.order_list(session, page=2, per_page=3)

    assert (page["total"], page["pages"], page["page"]) == (7, 3, 2)
    assert (page["has_prev"], page["has_next"]) == (True, True)
    assert (page["prev_page"], page["next_page"]) == (1, 3)


def test_the_middle_page_carries_the_middle_slice(session: SnakeSession) -> None:
    """The rows of page two are the fourth, fifth and sixth: an off-by-one here is invisible.

    Newest first, so the slice runs backwards through the references. The order is `placed_at` then
    the id, and the id is what makes it stable when the seven land in the same second — which they do
    here, and which is why the listing has a tiebreaker at all.
    """
    shop = _shop(session)
    for index in range(7):
        _place(session, shop, f"ORD-{index}")

    page = viewmodels.order_list(session, page=2, per_page=3)

    assert [row["reference"] for row in page["rows"]] == ["ORD-3", "ORD-2", "ORD-1"]


def test_the_edges_do_not_offer_a_step_that_does_not_exist(
    session: SnakeSession,
) -> None:
    """First page has no previous, last page has no next, and the last one is not full."""
    shop = _shop(session)
    for index in range(7):
        _place(session, shop, f"ORD-{index}")

    first = viewmodels.order_list(session, page=1, per_page=3)
    last = viewmodels.order_list(session, page=3, per_page=3)

    assert (first["has_prev"], first["has_next"]) == (False, True)
    assert (last["has_prev"], last["has_next"]) == (True, False)
    assert len(last["rows"]) == 1


def test_a_page_past_the_end_lands_on_the_last_one(session: SnakeSession) -> None:
    """A page number comes from the URL, so it is whatever somebody typed there.

    Clamping instead of answering an empty page is the useful behaviour: `?page=99` is a stale
    bookmark, and a blank listing reads as "there is nothing here" when there are seven orders.
    """
    shop = _shop(session)
    for index in range(7):
        _place(session, shop, f"ORD-{index}")

    page = viewmodels.order_list(session, page=99, per_page=3)

    assert page["page"] == 3
    assert page["has_next"] is False
    assert len(page["rows"]) == 1


def test_an_empty_listing_is_still_one_page(session: SnakeSession) -> None:
    """Zero rows is `1 of 1`, not `1 of 0`: a pager that says page 1 of 0 is a division that leaked."""
    _shop(session)

    page = viewmodels.order_list(session)

    assert (page["total"], page["pages"], page["page"]) == (0, 1, 1)
    assert (page["has_prev"], page["has_next"]) == (False, False)
    assert page["rows"] == []


def test_the_state_filter_narrows_the_listing_and_comes_back(
    session: SnakeSession,
) -> None:
    """The filter travels back in the page so the template can mark the selected option."""
    shop = _shop(session)
    _place(session, shop, "ORD-DRAFT")
    _order_in(session, shop, OrderState.CANCELLED, "ORD-GONE")

    page = viewmodels.order_list(session, state=OrderState.CANCELLED)

    assert page["state"] == "cancelled"
    assert page["total"] == 1
    assert [row["reference"] for row in page["rows"]] == ["ORD-GONE"]
    assert [option["value"] for option in page["states"]] == [
        state.value for state in OrderState
    ]


def test_no_filter_comes_back_as_empty_rather_than_none(session: SnakeSession) -> None:
    """`None` in a Jinja or Django template prints the word "None" into the `<option>` markup."""
    _shop(session)

    page = viewmodels.order_list(session)

    assert page["state"] == ""


def test_a_state_that_does_not_exist_is_no_filter_at_all(session: SnakeSession) -> None:
    """A hand-edited `?state=banana` shows everything instead of raising a `ValueError`.

    It cannot narrow to nothing the way an unknown id does: an unknown id is still a filter the
    engine can run, and an unknown state is a value the enum refuses to build at all. So the
    fallback is the unfiltered listing, decided once here rather than in two `try/except` blocks.
    """
    assert viewmodels.parse_state("banana") is None
    assert viewmodels.parse_state("") is None
    assert viewmodels.parse_state(None) is None
    assert viewmodels.parse_state("reserved") is OrderState.RESERVED


# ---- Failure travels through unchanged ----------------------------------------------------------


def test_an_order_that_does_not_exist_is_a_failure_and_not_an_empty_page(
    session: SnakeSession,
) -> None:
    """The web layer needs a 404, and an empty page is a 200 that says nothing is wrong.

    Every page keyed by an id has to agree on that, which is why all four are asserted together: one
    of them quietly returning a blank page is a link that 200s on a deleted order.
    """
    _shop(session)

    assert viewmodels.order_detail(session, 999) == Failure("not_found")
    assert viewmodels.order_form(session, 999) == Failure("not_found")
    assert viewmodels.order_delete_confirm(session, 999) == Failure("not_found")
    assert viewmodels.order_operation(session, 999) == Failure("not_found")


# ---- The detail ---------------------------------------------------------------------------------


def test_the_detail_carries_the_lines_with_the_sku_name_and_the_line_total(
    session: SnakeSession,
) -> None:
    """`quantity * unit_price` is one multiplication, and two templates would write it two ways."""
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1", wanted=3)

    page = viewmodels.order_detail(session, order_id)

    assert not isinstance(page, Failure)
    line = page["lines"][0]
    assert (line["sku_id"], line["sku_name"], line["quantity"]) == (
        shop.sku_id,
        "Widget",
        3,
    )
    assert (line["unit_price"], line["line_total"]) == ("10.00", "30.00")
    assert page["lines_total"] == "30.00"


def test_an_unbilled_order_has_no_invoice_and_says_so_without_a_none(
    session: SnakeSession,
) -> None:
    """A draft has no invoice, and the page has to be able to say that without printing "None".

    `invoice` is the one place a `None` is kept, and the distinction is deliberate: a template
    BRANCHES on a missing nested shape (`{% if invoice %}`) and PRINTS a missing scalar. So a scalar
    comes out as `""` and a shape comes out as `None`, and `has_invoice` is on the row for the
    listing, which carries no shape to branch on.
    """
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1")

    page = viewmodels.order_detail(session, order_id)

    assert not isinstance(page, Failure)
    assert page["invoice"] is None
    assert page["order"]["has_invoice"] is False


def test_a_billed_order_carries_its_invoice(session: SnakeSession) -> None:
    """The joint with `billing`, seen from the order: the LEFT JOIN that was null is now a row."""
    shop = _shop(session)
    order_id = _order_in(session, shop, OrderState.SETTLED, "ORD-1")

    page = viewmodels.order_detail(session, order_id)

    assert not isinstance(page, Failure)
    assert page["invoice"] is not None
    assert page["invoice"]["paid"] is True
    assert page["invoice"]["issued_at"].startswith("20")
    assert page["order"]["has_invoice"] is True


# ---- The form, which is create and update at once ------------------------------------------------


def test_the_create_form_offers_the_options_and_holds_no_order(
    session: SnakeSession,
) -> None:
    """Creating means every customer, warehouse and SKU to choose from, and nothing selected yet."""
    shop = _shop(session)

    page = viewmodels.order_form(session)

    assert not isinstance(page, Failure)
    assert page["is_update"] is False
    assert page["order"] is None
    assert page["lines"] == []
    assert [option["id"] for option in page["customers"]] == [shop.customer_id]
    assert [option["code"] for option in page["warehouses"]] == ["MAD"]
    assert [option["name"] for option in page["skus"]] == ["Widget"]
    assert page["skus"][0]["price"] == "10.00"


def test_the_update_form_carries_the_order_and_the_lines_it_is_editing(
    session: SnakeSession,
) -> None:
    """The same page with an id in it: same options, plus the order and the lines already on it."""
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1", wanted=4)

    page = viewmodels.order_form(session, order_id)

    assert not isinstance(page, Failure)
    assert page["is_update"] is True
    assert page["order"] is not None
    assert page["order"]["id"] == order_id
    assert [line["quantity"] for line in page["lines"]] == [4]


def test_the_customer_option_says_how_much_the_picker_needs_to_choose(
    session: SnakeSession,
) -> None:
    """A picker of customers is more useful with their order count than without it, and it is free.

    Free because `customer_orders` answers both in ONE statement — the count is a correlated
    aggregate over the inverse side, not a second query per customer.
    """
    shop = _shop(session)
    _place(session, shop, "ORD-1")
    _place(session, shop, "ORD-2")

    page = viewmodels.order_form(session)

    assert not isinstance(page, Failure)
    assert page["customers"][0]["username"] == "buyer"
    assert page["customers"][0]["order_count"] == 2


# ---- The delete confirmation --------------------------------------------------------------------


def test_an_order_with_lines_cannot_be_deleted_and_the_page_says_why(
    session: SnakeSession,
) -> None:
    """The FK is RESTRICT, so the button would fail after being pressed. The page refuses first.

    And it NAMES the lines rather than counting them, which is the opposite of what the inventory's
    confirmation does with its movements — on purpose. An order has a handful of lines and knowing
    which SKUs go with it is the answer somebody wants; a stock row has a year of movements and
    listing them is a page nobody reads.
    """
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1")

    page = viewmodels.order_delete_confirm(session, order_id)

    assert not isinstance(page, Failure)
    assert page["can_delete"] is False
    assert page["blocked"]
    assert page["line_count"] == 1
    assert [line["sku_name"] for line in page["lines"]] == ["Widget"]
    assert usecases.remove_order(session, order_id=order_id) == Failure("conflict")


def test_an_empty_order_can_be_deleted_and_the_page_offers_it(
    session: SnakeSession,
) -> None:
    """With nothing to orphan the delete goes through, and the page's boolean agrees with it."""
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1")
    assert usecases.remove_line(session, order_id=order_id, sku_id=shop.sku_id) is None

    page = viewmodels.order_delete_confirm(session, order_id)

    assert not isinstance(page, Failure)
    assert page["can_delete"] is True
    assert page["blocked"] == ""
    assert page["line_count"] == 0
    assert usecases.remove_order(session, order_id=order_id) is None


# ---- The operation page --------------------------------------------------------------------------


def test_the_operation_page_says_what_stock_each_line_can_actually_have(
    session: SnakeSession,
) -> None:
    """The page `for_update` is reached from: every line next to what the shelf holds for it.

    `available` is `quantity - reserved` and not `quantity`, which is the whole disagreement the
    reservation is about: units already promised to somebody else are still on the shelf.
    """
    shop = _shop(session, on_hand=10)
    assert not isinstance(
        usecases.reserve(session, order_id=_place(session, shop, "ORD-HELD", wanted=4)),
        Failure,
    )
    order_id = _place(session, shop, "ORD-1", wanted=2)

    page = viewmodels.order_operation(session, order_id)

    assert not isinstance(page, Failure)
    line = page["lines"][0]
    assert (line["on_hand"], line["held"], line["available"]) == (10, 4, 6)
    assert line["is_short"] is False
    assert page["can_reserve"] is True
    assert page["reserve_warning"] == ""


def test_the_operation_page_warns_when_a_line_is_short_without_refusing(
    session: SnakeSession,
) -> None:
    """A shortage is a WARNING and not a `can_reserve = False`, and the difference is the lock.

    This read is taken outside the lock, so between drawing the page and pressing the button the
    units can be taken by somebody else — or released back. The operation reads the rows AGAIN under
    `for_update` and decides there. A page that hid the button would be deciding with worse
    information than the operation has, and it would be wrong in both directions.
    """
    shop = _shop(session, on_hand=1)
    order_id = _place(session, shop, "ORD-1", wanted=5)

    page = viewmodels.order_operation(session, order_id)

    assert not isinstance(page, Failure)
    assert page["lines"][0]["is_short"] is True
    assert page["can_reserve"] is True
    assert page["reserve_warning"]
    assert usecases.reserve(session, order_id=order_id) == Failure("conflict")


def test_a_pair_the_warehouse_has_never_held_reads_as_zero_and_not_as_missing(
    session: SnakeSession,
) -> None:
    """No stock row means zero units, which is a shortage like any other — exactly what `reserve` says."""
    shop = _shop(session)
    other = inventory.create_sku(
        session,
        name="Never stocked",
        kind=SkuKind.DIGITAL,
        price=Decimal("5.00"),
        weight_kg=0.0,
        lead_time=timedelta(days=1),
    )
    assert not isinstance(other, Failure), other
    order = usecases.place_order(
        session,
        reference="ORD-1",
        customer_id=shop.customer_id,
        warehouse_id=shop.warehouse_id,
        lines=[(other.id, 1)],
    )
    assert not isinstance(order, Failure), order

    page = viewmodels.order_operation(session, order.id)

    assert not isinstance(page, Failure)
    assert (page["lines"][0]["on_hand"], page["lines"][0]["available"]) == (0, 0)
    assert page["lines"][0]["is_short"] is True


def test_the_operation_page_offers_only_the_customers_own_subscriptions(
    session: SnakeSession,
) -> None:
    """`settle` refuses an invoice hung off somebody else's subscription, so the picker cannot offer one.

    Nothing in the schema stops it — `Order.invoice_id` does not know whose subscription the invoice
    belongs to — so the rule lives in the use case, and the page has to narrow the options to match
    it. A picker showing every subscription in the database is a 409 waiting to be clicked.
    """
    shop = _shop(session)
    stranger = session.add(
        User(username="stranger", email="stranger@demo.dev", password_hash="x")
    )
    session.commit()
    other_plan = session.add(Plan(name="plan-other", price_cents=100))
    session.commit()
    billing.subscribe(session, stranger.id, other_plan.id)
    order_id = _order_in(session, shop, OrderState.RESERVED, "ORD-1")

    page = viewmodels.order_operation(session, order_id)

    assert not isinstance(page, Failure)
    assert [option["id"] for option in page["subscriptions"]] == [shop.subscription_id]
    assert page["subscriptions"][0]["plan"] == "plan-basic"
    assert page["can_settle"] is True


def test_a_customer_with_no_subscription_is_not_offered_a_settlement(
    session: SnakeSession,
) -> None:
    """The one place the page's boolean is NARROWER than the row's, and it has to be.

    The row's `can_settle` is the state rule, which is all a listing can know. This page has read the
    subscriptions, so it knows something the listing does not: there is nothing to issue the invoice
    against, and `settle` would answer `not_found` after the button was pressed.
    """
    shop = _shop(session)
    orphan = session.add(
        User(username="orphan", email="orphan@demo.dev", password_hash="x")
    )
    session.commit()
    order = usecases.place_order(
        session,
        reference="ORD-1",
        customer_id=orphan.id,
        warehouse_id=shop.warehouse_id,
        lines=[(shop.sku_id, 1)],
    )
    assert not isinstance(order, Failure), order
    assert not isinstance(usecases.reserve(session, order_id=order.id), Failure)

    page = viewmodels.order_operation(session, order.id)

    assert not isinstance(page, Failure)
    assert page["subscriptions"] == []
    assert page["order"]["can_settle"] is True
    assert page["can_settle"] is False
    assert page["settle_blocked"]


def test_the_blocked_reasons_are_empty_exactly_when_the_operation_is_offered(
    session: SnakeSession,
) -> None:
    """A reason and its boolean are two halves of one answer, so they cannot disagree.

    A non-empty reason next to an enabled button is a page that explains why it is doing what it is
    not doing, and an empty reason next to a disabled one is a dead control with no explanation.
    Both are the kind of thing that looks fine until somebody reads it.
    """
    shop = _shop(session)
    for state in OrderState:
        order_id = _order_in(session, shop, state, f"ORD-{state.value}")
        page = viewmodels.order_operation(session, order_id)

        assert not isinstance(page, Failure)
        for key, reason in (
            ("can_reserve", "reserve_blocked"),
            ("can_settle", "settle_blocked"),
            ("can_cancel", "cancel_blocked"),
        ):
            offered = page[key]  # type: ignore[literal-required]
            blocked = page[reason]  # type: ignore[literal-required]
            assert offered is not bool(blocked), f"{state.value}: {key} / {reason}"


# ---- The query budget ---------------------------------------------------------------------------


def _queries_of_a_list_page(session: SnakeSession, rows: int) -> int:
    """Builds a full list page over `rows` orders and returns how many statements it took."""
    shop = _shop(session)
    for index in range(rows):
        _place(session, shop, f"ORD-{index:03d}")
    with capture_queries() as collector:
        page = viewmodels.order_list(session, per_page=rows + 1)
    assert len(page["rows"]) == rows, "the budget was measured over the wrong page"
    return collector.report().count


def test_the_list_page_costs_the_same_at_three_orders_and_at_thirty(
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


def test_the_list_page_is_two_statements(session: SnakeSession) -> None:
    """And what that constant IS: the count and the page of rows. There is no third.

    The pilot's listing costs three because its filter is a TABLE of warehouses. This one's filter is
    an ENUM, so the options are a Python constant and the page is one statement cheaper — which is
    worth writing down, because it is the reason the two numbers differ and not an accident.
    """
    assert _queries_of_a_list_page(session, 5) == 2


def test_the_operation_page_costs_the_same_at_one_line_and_at_twenty(
    session: SnakeSession,
) -> None:
    """The page reads three domains, and none of the three reads grows with the number of lines.

    The stock is fetched for the WAREHOUSE in one statement, not one per line. That is the choice
    this number pins: a lookup per line would be correct, invisible on a two-line order, and an N+1
    on the page whose whole subject is what happens under load.
    """
    shop = _shop(session, on_hand=100)
    skus = [shop.sku_id]
    for index in range(19):
        extra = inventory.create_sku(
            session,
            name=f"Widget {index:02d}",
            kind=SkuKind.PHYSICAL,
            price=Decimal("1.00"),
            weight_kg=1.0,
            lead_time=timedelta(days=1),
        )
        assert not isinstance(extra, Failure), extra
        assert not isinstance(
            inventory.count_stock(
                session, warehouse_id=shop.warehouse_id, sku_id=extra.id, on_hand=5
            ),
            Failure,
        )
        skus.append(extra.id)
    slim = _place(session, shop, "ORD-SLIM")
    fat = usecases.place_order(
        session,
        reference="ORD-FAT",
        customer_id=shop.customer_id,
        warehouse_id=shop.warehouse_id,
        lines=[(sku_id, 1) for sku_id in skus],
    )
    assert not isinstance(fat, Failure), fat

    with capture_queries() as one:
        viewmodels.order_operation(session, slim)
    with capture_queries() as many:
        page = viewmodels.order_operation(session, fat.id)

    assert not isinstance(page, Failure)
    assert len(page["lines"]) == 20
    # Flat, and what the constant IS: the order, the lines and their existence check, the
    # warehouse and its stock, the subscriptions and their invoices. Seven is a lot for one page and
    # every one of them is named in the docstring, which is the deal — a number nobody can account
    # for is a number that grows.
    #
    # The seventh arrived with `attach`, and it is ONE because `invoices_of_customer` walks
    # `Invoice.subscription.user_id` as a JOIN. Listed per subscription it would have been the N+1
    # this very test exists to head off, and the number here would have moved with the customer
    # rather than with the page.
    assert one.report().count == many.report().count == 7


def test_the_detail_page_costs_the_same_at_one_line_and_at_twenty(
    session: SnakeSession,
) -> None:
    """The to-many over the COMPOSITE key is ONE extra statement, however many lines come back."""
    shop = _shop(session)
    skus = [shop.sku_id]
    for index in range(19):
        extra = inventory.create_sku(
            session,
            name=f"Widget {index:02d}",
            kind=SkuKind.PHYSICAL,
            price=Decimal("1.00"),
            weight_kg=1.0,
            lead_time=timedelta(days=1),
        )
        assert not isinstance(extra, Failure), extra
        skus.append(extra.id)
    slim = _place(session, shop, "ORD-SLIM")
    fat = usecases.place_order(
        session,
        reference="ORD-FAT",
        customer_id=shop.customer_id,
        warehouse_id=shop.warehouse_id,
        lines=[(sku_id, 1) for sku_id in skus],
    )
    assert not isinstance(fat, Failure), fat

    with capture_queries() as one:
        viewmodels.order_detail(session, slim)
    with capture_queries() as many:
        page = viewmodels.order_detail(session, fat.id)

    assert not isinstance(page, Failure)
    assert len(page["lines"]) == 20
    # Three, and the third is the existence check `order_lines` repeats after `get_order` has
    # already done it. That is the price of the use-case seam, written down so it stays a price
    # somebody chose rather than one nobody noticed.
    assert one.report().count == many.report().count == 3


# ---- The rule that only a real server can show ---------------------------------------------------


def test_reading_the_page_before_the_operation_passes_in_silence_on_this_server(
    postgres_pair: tuple[SnakeSession, SnakeSession],
) -> None:
    """THE TRAP, pinned as a green test because green is exactly what makes it a trap.

    Drawing the operation page and then performing the operation ON THE SAME SESSION spends the one
    moment `reserve` needed: `SET TRANSACTION ISOLATION LEVEL` is only accepted before the
    transaction has read anything, and a view model is a read.

    And Postgres does not complain. Measured on 15: the statement is refused only when it would
    CHANGE the level, so asking for the level the transaction already has is accepted and does
    nothing. A stock server defaults to `READ COMMITTED`, which is the level `reserve` asks for, so
    the sequence below reserves correctly — by luck, not by declaration.

    That is the whole reason the rule is written in capitals in the module docstring instead of being
    left to be discovered. What has silently changed is that the operation stopped declaring its
    isolation and started inheriting whatever the connection had, and the test below is the same
    sequence on a connection that had something else.
    """
    session, _ = postgres_pair
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1")

    page = viewmodels.order_operation(session, order_id)
    assert not isinstance(page, Failure)

    reserved = usecases.reserve(session, order_id=order_id)

    assert not isinstance(reserved, Failure), reserved
    assert reserved.state is OrderState.RESERVED


def test_reading_the_page_first_breaks_the_operation_where_the_default_is_not_read_committed(
    postgres_pair: tuple[SnakeSession, SnakeSession],
) -> None:
    """THE SAME SEQUENCE where the server default differs, which is where the demos are deployed.

    `default_transaction_isolation` is a server-wide setting, and MySQL — which these demos also run
    on — defaults to `REPEATABLE READ`. So the transaction the read opens is not necessarily the one
    `reserve` wants, and asking to move it after the read is the case Postgres DOES refuse:
    `ActiveSqlTransaction`, raised from three layers below the handler that asked.

    The level is set by hand here rather than by reconfiguring the server, and that is the honest
    shape of the test: it imitates the connection a differently configured engine would hand over,
    without asking a shared database to change its mind for one run.

    Then the fix, which is the whole reason the rule is livable: closing the read's transaction hands
    the operation a clean one, and the identical call goes through. A demo gets that for free by
    giving the GET and the POST a session each, which is what all three frameworks already do.
    """
    import psycopg2

    session, _ = postgres_pair
    shop = _shop(session)
    order_id = _place(session, shop, "ORD-1")
    session.set_isolation(SnakeIsolation.REPEATABLE_READ)

    page = viewmodels.order_operation(session, order_id)
    assert not isinstance(page, Failure)

    with pytest.raises(psycopg2.errors.ActiveSqlTransaction):
        usecases.reserve(session, order_id=order_id)

    session.rollback()
    assert not isinstance(usecases.reserve(session, order_id=order_id), Failure)


# ---- The customer sheet --------------------------------------------------------------------------


def test_the_customer_sheet_is_made_of_primitives(session: SnakeSession) -> None:
    """It walks a to-many of orders and a to-many of lines under it, and neither leaks out."""
    shop = _shop(session)
    _place(session, shop, "ORD-1")

    page = viewmodels.customer_sheet(session, shop.customer_id)

    assert not isinstance(page, Failure)
    _assert_only_primitives(page)


def test_the_sheet_names_the_sku_of_a_line_the_query_did_not_include(
    session: SnakeSession,
) -> None:
    """The orders arrive with their LINES and the lines arrive without their SKU, on purpose.

    So the name comes from the catalogue read once, and this is the assertion that would break if
    somebody reached for `line.sku.name` instead — which on this ORM does not fire a hidden query,
    it raises. Same row shape as the order sheet's, different builder, and a template cannot tell.
    """
    shop = _shop(session)
    _place(session, shop, "ORD-1", wanted=3)

    page = viewmodels.customer_sheet(session, shop.customer_id)

    assert not isinstance(page, Failure)
    line = page["orders"][0]["lines"][0]
    assert line["sku_id"] == shop.sku_id
    assert line["sku_name"] == "Widget"
    assert line["quantity"] == 3
    assert line["unit_price"] == "10.00" and line["line_total"] == "30.00"


def test_the_heading_is_the_report_row_the_sheet_was_reached_from(
    session: SnakeSession,
) -> None:
    """The two figures in the heading are the SAME two the report prints for that customer.

    Not "equal by arithmetic" — the same statement produced both, which is why they cannot come to
    different conclusions about whether a cancelled order counts. Adding them up from the orders on
    the sheet would be a second answer to a question the engine has already answered.
    """
    shop = _shop(session)
    _place(session, shop, "ORD-1", wanted=2)
    _place(session, shop, "ORD-2", wanted=3)

    sheet = viewmodels.customer_sheet(session, shop.customer_id)
    reported = viewmodels.order_report(session)["customers"]

    assert not isinstance(sheet, Failure)
    row = next(row for row in reported if row["id"] == shop.customer_id)
    assert sheet["username"] == row["username"] == "buyer"
    assert sheet["order_count"] == row["order_count"] == 2
    assert sheet["ordered_total"] == row["ordered_total"] == "50.00"


def test_each_order_shows_what_its_lines_add_up_to_beside_what_is_stored(
    session: SnakeSession,
) -> None:
    """`lines_total` is summed from the page and `total` is the column the writes keep in step.

    Showing both is how a reader of these demos sees that a derived-and-stored value is a claim
    somebody has to hold to, which is the same pairing the order sheet makes one storey down.
    """
    shop = _shop(session)
    _place(session, shop, "ORD-1", wanted=4)

    page = viewmodels.customer_sheet(session, shop.customer_id)

    assert not isinstance(page, Failure)
    order = page["orders"][0]
    assert order["reference"] == "ORD-1"
    assert order["line_count"] == 1
    assert order["lines_total"] == order["total"] == "40.00"
    assert order["state_label"] == "Draft" and order["has_invoice"] is False


def test_a_customer_with_no_orders_is_a_page_and_an_unknown_one_is_a_failure(
    session: SnakeSession,
) -> None:
    """The distinction the endpoint makes and an empty list cannot: never ordered, versus never existed.

    Both would be `{"orders": []}` on a page that skipped the check, and only one of the two means
    the link that got you here is wrong.
    """
    _shop(session)
    quiet = session.add(
        User(username="quiet", email="quiet@demo.dev", password_hash="x")
    )
    session.commit()

    page = viewmodels.customer_sheet(session, quiet.id)
    missing = viewmodels.customer_sheet(session, 9999)

    assert not isinstance(page, Failure)
    assert page["username"] == "quiet"
    assert page["orders"] == [] and page["order_count"] == 0
    assert isinstance(missing, Failure) and missing.reason == "not_found"


def _queries_of_a_customer_sheet(session: SnakeSession, orders: int) -> int:
    """Builds the sheet over `orders` placed orders and returns how many statements it took."""
    shop = _shop(session)
    for index in range(orders):
        _place(session, shop, f"ORD-{index:03d}")
    with capture_queries() as collector:
        page = viewmodels.customer_sheet(session, shop.customer_id)
    assert not isinstance(page, Failure)
    assert len(page["orders"]) == orders, "the budget was measured over the wrong sheet"
    return collector.report().count


def test_the_customer_sheet_costs_the_same_at_three_orders_and_at_thirty(
    make_session: Callable[[], SnakeSession],
) -> None:
    """THE POINT OF THE PAGE, asserted: every line of every order in ONE extra statement.

    The pages could reach this answer already, one order sheet at a time — which is one request per
    order, and the gap the API had been closing on its own. What must never change is the SLOPE.
    """
    small, large = make_session(), make_session()
    try:
        assert _queries_of_a_customer_sheet(small, 3) == _queries_of_a_customer_sheet(
            large, 30
        )
    finally:
        small.close()
        large.close()


def test_the_customer_sheet_is_five_statements(session: SnakeSession) -> None:
    """And what that constant IS: the probe, the orders, the lines, the customers, the SKUs.

    The probe is `orders_of_customer` proving the customer exists before it reads, which is what the
    404 is made of. The number is written down once, here, so that the day it moves somebody has to
    say why.
    """
    assert _queries_of_a_customer_sheet(session, 4) == 5
