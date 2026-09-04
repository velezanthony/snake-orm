"""The orders domain over Django's test client: the six pages, driven the way a browser drives them.

The logic lives in `shared` and its own suite already pins it — the pager's arithmetic, the flattened
relations, the `can_*` rules and the three operations all have tests of their own. What is checked
HERE is the part only the framework can get wrong: that a route carries what the page needs, that a
`Failure` reason becomes the status it maps to, that a write reaches the real database, and that the
shell puts a sidebar on every one of the pages.

AND ONE THING THAT IS NOT LIKE ANY OTHER APP'S TESTS. `test_the_operation_is_handed_a_transaction_of_its_own`
exists to fail when somebody deletes a `session.rollback()` from a POST handler in `views.py`. That
line looks like dead code — on this machine deleting it breaks nothing, because Postgres accepts a
`SET TRANSACTION ISOLATION LEVEL` that changes nothing and a stock Postgres already sits at the level
the operations ask for. It breaks on a server whose default is anything else, MySQL's `REPEATABLE
READ` included, where the losing customer of a race stops being told `conflict` and dies with a
driver serialisation error instead. So the test imitates that server on one request rather than
asking a shared database to change its mind.

`SimpleTestCase`: the business data does NOT touch Django's ORM; SnakeORM carries it.
"""

from __future__ import annotations


import csv
import re
from typing import Literal
from unittest.mock import patch

from django.http import StreamingHttpResponse
from django.test import Client, SimpleTestCase, override_settings

from snakeorm import SnakeIsolation, SnakeQuery, SnakeSession
from snakeorm.debug import capture_queries
from shared import config
from shared.models import Invoice, Stock, Subscription

from apps.blog import middleware, seed
from apps.orders.models import Order, OrderLine, OrderState


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"])
class OrdersPagesTests(SimpleTestCase):
    """The five pages of the taxonomy plus the operation page the whole domain was built for.

    `SimpleTestCase` with no databases declared, for the same reason as the pilot's page tests: the
    business data does not touch Django's ORM, SnakeORM carries it.
    """

    databases: set[str] | Literal["__all__"] = set()

    def setUp(self) -> None:
        """Leaves the SnakeORM database in its seeded state before each test."""
        seed.reset_and_seed()
        self.client = Client()

    # --- helpers ---------------------------------------------------------------------------------

    def _new_session(self) -> SnakeSession:
        """A direct SnakeORM session, to assert against the database rather than against the page."""
        return config.make_session("django")

    def _html(self, url: str, status: int = 200) -> str:
        """The decoded body of a GET, having checked the status first (a 500 is not a page)."""
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return response.content.decode()

    def _ids_in(self, html: str) -> list[int]:
        """The orders a listing links to, read off its detail hrefs, in the order they appear."""
        return [int(found) for found in re.findall(r"/orders/detail/(\d+)/", html)]

    def _states_of(self, order_ids: list[int]) -> set[OrderState]:
        """The states of those orders STRAIGHT FROM THE DATABASE, not off the badges on the page.

        Reading the filter's effect out of the HTML would prove the template printed what it was
        handed, which is not the question: what the filter has to be right about is which rows came
        back at all.
        """
        session = self._new_session()
        try:
            return {
                order.state
                for order in session.all(
                    SnakeQuery(Order).filter(Order.id.in_(order_ids))
                )
            }
        finally:
            session.close()

    def _state_of(self, order_id: int) -> OrderState | None:
        """One order's state from the database, or `None` if the order is gone."""
        session = self._new_session()
        try:
            order = session.first(SnakeQuery(Order).filter(Order.id == order_id))
            return None if order is None else order.state
        finally:
            session.close()

    def _an_invoice_of(self, subscription_id: int) -> int:
        """An invoice the seeding already raised against that subscription.

        Read rather than created, because `attach_invoice` is about billing against an invoice that
        ALREADY exists — creating one here would be testing the operation against a fixture built
        for it, which is the shape that passes whatever the operation does.
        """
        session = self._new_session()
        try:
            invoice = session.first(
                SnakeQuery(Invoice)
                .filter(Invoice.subscription_id == subscription_id)
                .order_by(Invoice.id.asc())
            )
            self.assertIsNotNone(invoice, "the seeding left that subscription unbilled")
            assert invoice is not None
            return invoice.id
        finally:
            session.close()

    def _levels(self, warehouse_id: int, sku_id: int) -> tuple[int, int]:
        """The `(on_hand, reserved)` of a stock pair, straight from the database."""
        session = self._new_session()
        try:
            stock = session.first(
                SnakeQuery(Stock).filter(
                    Stock.warehouse_id == warehouse_id, Stock.sku_id == sku_id
                )
            )
            self.assertIsNotNone(stock, "that stock pair is not there")
            assert stock is not None
            return stock.on_hand, stock.reserved
        finally:
            session.close()

    def _line_count(self, order_id: int) -> int:
        """How many lines an order has, from the database."""
        session = self._new_session()
        try:
            return len(
                session.all(
                    SnakeQuery(OrderLine).filter(OrderLine.order_id == order_id)
                )
            )
        finally:
            session.close()

    def _an_order_in(self, state: OrderState) -> int:
        """The lowest-numbered seeded order in a given state, chosen deterministically.

        The seeder walks the five states EXHAUSTIVELY before it starts drawing at random, so every
        state is guaranteed to be represented whatever the scale. That guarantee is what lets these
        tests name a state instead of hunting for one.
        """
        session = self._new_session()
        try:
            order = session.first(
                SnakeQuery(Order).filter(Order.state == state).order_by(Order.id.asc())
            )
            self.assertIsNotNone(order, f"the seeding left no {state.value} order")
            assert order is not None
            return order.id
        finally:
            session.close()

    def _somewhere_to_order_from(self) -> tuple[int, int, int, int]:
        """`(customer_id, subscription_id, warehouse_id, sku_id)` an order can be driven end to end on.

        The customer comes FROM a subscription rather than the other way round, because `settle`
        bills the order against a subscription of the order's own customer and refuses anybody
        else's. The pair comes from a stock row with plenty on the shelf, so the reservation is
        deciding on the operation and not on the fixture.
        """
        session = self._new_session()
        try:
            subscription = session.first(
                SnakeQuery(Subscription).order_by(Subscription.id.asc())
            )
            stock = session.first(
                SnakeQuery(Stock)
                .filter(Stock.on_hand > 20)
                .order_by(Stock.warehouse_id.asc(), Stock.sku_id.asc())
            )
            self.assertIsNotNone(subscription, "the seeding left no subscriptions")
            self.assertIsNotNone(stock, "the seeding left no well-stocked pair")
            assert subscription is not None and stock is not None
            return (
                subscription.user_id,
                subscription.id,
                stock.warehouse_id,
                stock.sku_id,
            )
        finally:
            session.close()

    def _place(
        self,
        *,
        reference: str,
        customer_id: int,
        warehouse_id: int,
        sku_id: int,
        units: int = 3,
    ) -> int:
        """Places a one-line order THROUGH THE CREATE PAGE and returns its id off the redirect.

        Through the page and not through the use case on purpose: every operation test then starts
        from an order this demo really made, so a create that silently stopped writing lines would
        take the operation tests down with it instead of leaving them green over a fixture.
        """
        created = self.client.post(
            "/orders/create/",
            {
                "reference": reference,
                "customer": customer_id,
                "warehouse": warehouse_id,
                "line_sku": [sku_id, "", ""],
                "line_quantity": [str(units), "", ""],
            },
        )
        self.assertEqual(created.status_code, 302, created.content)
        return int(created.headers["Location"].split("/")[3])

    # --- list -------------------------------------------------------------------------------------

    def test_the_listing_renders_rows_and_a_pager(self) -> None:
        """The list page paints orders and the pager that says which page of how many they are."""
        html = self._html("/orders/list/")

        self.assertIn('aria-label="Orders"', html)
        self.assertTrue(self._ids_in(html), "the listing linked to no order")
        self.assertIn("Page 1 of", html)
        # The first page has no previous, and the edge is a span rather than an <a> without href:
        # a link with nothing to point at is skipped by the keyboard entirely.
        self.assertIn(
            '<span class="btn btn-ghost btn-md" aria-disabled="true">Previous</span>',
            html,
        )

    def test_the_state_filter_narrows_the_listing(self) -> None:
        """`?state=` leaves only that state's orders, and the option comes back selected."""
        html = self._html("/orders/list/?state=cancelled")

        ids = self._ids_in(html)
        self.assertTrue(ids)
        self.assertEqual(self._states_of(ids), {OrderState.CANCELLED})
        self.assertIn('<option value="cancelled" selected>', html)

    def test_a_state_nobody_has_heard_of_shows_everything(self) -> None:
        """A typo in a hand-edited URL is not a 500 and not an empty table: it is no filter at all.

        `parse_state` chose that over raising, and the reason is worth keeping a test on: an unknown
        state cannot be turned into a filter at all — the enum refuses to build it — so the only
        alternatives were "show everything" and a 500 on a query string somebody mistyped.
        """
        typo = self._html("/orders/list/?state=nonsense")

        self.assertEqual(self._ids_in(typo), self._ids_in(self._html("/orders/list/")))
        for state in OrderState:
            self.assertNotIn(f'<option value="{state.value}" selected>', typo)

    def test_the_second_page_shows_other_orders(self) -> None:
        """`?page=2` is a different slice, not the same one drawn twice."""
        first = self._html("/orders/list/")
        self.assertNotIn(
            '<span class="btn btn-ghost btn-md" aria-disabled="true">Next</span>',
            first,
            "this test needs more than one page of orders (DEMO_SCALE=minimal seeds a single one)",
        )

        second = self._html("/orders/list/?page=2")

        self.assertIn("Page 2 of", second)
        self.assertTrue(self._ids_in(second))
        self.assertEqual(set(self._ids_in(first)) & set(self._ids_in(second)), set())

    # --- detail -----------------------------------------------------------------------------------

    def test_the_detail_renders_the_order_with_its_parties_and_its_lines(self) -> None:
        """A real order paints its two to-one hops flattened and the to-many keyed by order and SKU."""
        order_id = self._an_order_in(OrderState.SETTLED)

        html = self._html(f"/orders/detail/{order_id}/")

        self.assertIn('aria-label="Lines of this order"', html)
        self.assertIn("Lines add up to", html)
        self.assertIn(f"/orders/update/{order_id}/", html)
        self.assertIn(f"/orders/delete/{order_id}/", html)

    def test_an_order_that_is_not_there_answers_404(self) -> None:
        """`not_found` from the view model becomes a 404 with the error page, not an empty detail."""
        response = self.client.get("/orders/detail/999999/")

        self.assertEqual(response.status_code, 404)
        self.assertIn("That order does not exist", response.content.decode())

    # --- create -----------------------------------------------------------------------------------

    def test_placing_an_order_writes_it_and_its_lines_and_lands_on_it(self) -> None:
        """The form posts three parties and a line, the rows appear in the database, the redirect finds it."""
        customer_id, _, warehouse_id, sku_id = self._somewhere_to_order_from()

        order_id = self._place(
            reference="DJ-0001",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            units=4,
        )

        self.assertEqual(self._state_of(order_id), OrderState.DRAFT)
        self.assertEqual(self._line_count(order_id), 1)
        self.assertEqual(
            self.client.get(f"/orders/detail/{order_id}/").status_code, 200
        )

    def test_an_order_with_no_lines_is_refused_and_writes_nothing(self) -> None:
        """The reference is free and the form still cannot be posted: an order with no lines is not one."""
        customer_id, _, warehouse_id, _ = self._somewhere_to_order_from()

        refused = self.client.post(
            "/orders/create/",
            {
                "reference": "DJ-EMPTY",
                "customer": customer_id,
                "warehouse": warehouse_id,
                "line_sku": ["", "", ""],
                "line_quantity": ["", "", ""],
            },
        )

        self.assertEqual(refused.status_code, 200)
        self.assertIn(
            "An order with no lines is not an order", refused.content.decode()
        )
        session = self._new_session()
        try:
            self.assertIsNone(
                session.first(SnakeQuery(Order).filter(Order.reference == "DJ-EMPTY"))
            )
        finally:
            session.close()

    def test_a_reference_that_is_already_taken_answers_409(self) -> None:
        """`conflict` is the one refusal another request can turn true while this form is being typed."""
        customer_id, _, warehouse_id, sku_id = self._somewhere_to_order_from()
        self._place(
            reference="DJ-TWICE",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
        )

        again = self.client.post(
            "/orders/create/",
            {
                "reference": "DJ-TWICE",
                "customer": customer_id,
                "warehouse": warehouse_id,
                "line_sku": [sku_id, "", ""],
                "line_quantity": ["1", "", ""],
            },
        )

        self.assertEqual(again.status_code, 409)
        self.assertIn("already an order called DJ-TWICE", again.content.decode())

    # --- update -----------------------------------------------------------------------------------

    def test_a_line_can_be_moved_and_removed_one_submit_at_a_time(self) -> None:
        """Both line use cases are reachable, and the page tells them apart by the FIELDS posted."""
        customer_id, _, warehouse_id, sku_id = self._somewhere_to_order_from()
        order_id = self._place(
            reference="DJ-LINES",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            units=2,
        )

        moved = self.client.post(
            f"/orders/update/{order_id}/", {"sku": sku_id, "quantity": 9}
        )
        self.assertEqual(moved.status_code, 302)
        self.assertEqual(self._line_count(order_id), 1)

        dropped = self.client.post(f"/orders/update/{order_id}/", {"remove": sku_id})

        self.assertEqual(dropped.status_code, 302)
        self.assertEqual(self._line_count(order_id), 0)

    def test_the_update_form_locks_the_three_things_an_order_cannot_change(
        self,
    ) -> None:
        """Reference, customer and warehouse are what the lines were priced against: not editable."""
        order_id = self._an_order_in(OrderState.DRAFT)

        html = self._html(f"/orders/update/{order_id}/")

        self.assertIn('id="reference" name="reference" disabled', html)
        self.assertIn('id="customer" name="customer" disabled', html)
        self.assertIn('id="warehouse" name="warehouse" disabled', html)

    def test_a_billed_order_refuses_a_line_edit_in_words(self) -> None:
        """`conflict` maps to 409 on the page that offered the button, not to a blank error."""
        order_id = self._an_order_in(OrderState.SETTLED)
        session = self._new_session()
        try:
            line = session.first(
                SnakeQuery(OrderLine).filter(OrderLine.order_id == order_id)
            )
            self.assertIsNotNone(line, "the seeded settled order has no lines")
            assert line is not None
            sku_id = line.sku_id
        finally:
            session.close()

        refused = self.client.post(
            f"/orders/update/{order_id}/", {"sku": sku_id, "quantity": 99}
        )

        self.assertEqual(refused.status_code, 409)
        self.assertIn("has been billed", refused.content.decode())

    # --- delete -----------------------------------------------------------------------------------

    def test_deleting_an_order_that_has_lines_is_refused_in_words(self) -> None:
        """FK RESTRICT: the confirmation explains it and the POST answers 409, with the order intact."""
        order_id = self._an_order_in(OrderState.DRAFT)

        confirm = self._html(f"/orders/delete/{order_id}/")
        self.assertIn("cancelled, not deleted", confirm)
        self.assertIn('aria-disabled="true">Delete</span>', confirm)

        refused = self.client.post(f"/orders/delete/{order_id}/")

        self.assertEqual(refused.status_code, 409)
        self.assertIsNotNone(self._state_of(order_id))

    def test_an_order_with_no_lines_left_can_be_deleted(self) -> None:
        """The other side of the same fork: nothing hangs off it, so the confirmation offers a button."""
        customer_id, _, warehouse_id, sku_id = self._somewhere_to_order_from()
        order_id = self._place(
            reference="DJ-GONE",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
        )
        self.client.post(f"/orders/update/{order_id}/", {"remove": sku_id})

        confirm = self._html(f"/orders/delete/{order_id}/")
        self.assertIn("Yes, delete it", confirm)
        deleted = self.client.post(f"/orders/delete/{order_id}/")

        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(deleted.headers["Location"], "/orders/list/")
        self.assertIsNone(self._state_of(order_id))

    # --- operate ----------------------------------------------------------------------------------

    def test_the_chooser_answers_the_sidebar_link_with_the_drafts(self) -> None:
        """`/orders/operate/` carries no id, so it lists the state all three operations start from."""
        html = self._html("/orders/operate/")

        ids = self._ids_in(html)
        self.assertTrue(ids)
        self.assertEqual(self._states_of(ids), {OrderState.DRAFT})
        self.assertIn("Operate an order", html)
        self.assertIn(f"/orders/operate/{ids[0]}/", html)

    def test_the_operation_page_shows_the_stock_behind_every_line(self) -> None:
        """On hand, held and available, because the gap between the first two is where the race lives."""
        order_id = self._an_order_in(OrderState.DRAFT)

        html = self._html(f"/orders/operate/{order_id}/")

        self.assertIn('aria-label="Lines against the stock they would take"', html)
        self.assertIn("On hand", html)
        self.assertIn("Available", html)
        self.assertIn("Reserve the units", html)

    def test_reserving_holds_the_units_on_the_real_stock_row(self) -> None:
        """The point of the domain: `reserved` on the warehouse's own row goes up by what was ordered."""
        customer_id, _, warehouse_id, sku_id = self._somewhere_to_order_from()
        order_id = self._place(
            reference="DJ-HOLD",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            units=6,
        )
        on_hand, reserved = self._levels(warehouse_id, sku_id)

        held = self.client.post(f"/orders/operate/{order_id}/reserve/")

        self.assertEqual(held.status_code, 302)
        self.assertEqual(held.headers["Location"], f"/orders/operate/{order_id}/")
        self.assertEqual(self._state_of(order_id), OrderState.RESERVED)
        # `on_hand` does not move: the units are still on the shelf, they are just promised.
        self.assertEqual(self._levels(warehouse_id, sku_id), (on_hand, reserved + 6))

    def test_settling_a_reserved_order_reaches_settled(self) -> None:
        """The four-step operation end to end: invoice issued, money taken, units shipped, order closed."""
        customer_id, subscription_id, warehouse_id, sku_id = (
            self._somewhere_to_order_from()
        )
        order_id = self._place(
            reference="DJ-PAID",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            units=5,
        )
        self.client.post(f"/orders/operate/{order_id}/reserve/")
        on_hand, reserved = self._levels(warehouse_id, sku_id)

        settled = self.client.post(
            f"/orders/operate/{order_id}/settle/", {"subscription": subscription_id}
        )

        self.assertEqual(settled.status_code, 302)
        self.assertEqual(self._state_of(order_id), OrderState.SETTLED)
        # Shipping takes the units off the shelf AND off the hold: they left the building.
        self.assertEqual(
            self._levels(warehouse_id, sku_id), (on_hand - 5, reserved - 5)
        )
        self.assertIn("Issued", self._html(f"/orders/operate/{order_id}/"))

    def test_billing_an_open_order_against_an_existing_invoice_reaches_invoiced(
        self,
    ) -> None:
        """The plain half of the joint with billing, over HTTP: it links the two rows and stops.

        No savepoint and no money moves. `settle` is the half that issues the invoice, charges and
        rewinds the shipment if the card is declined; this one bills against a bill that is already
        there, which is what a customer with an open account does every month.

        The invoice comes off the seeding, and that is the point of the operation existing at all:
        the page can only offer a choice it has a cheap way to list, which is why it needed a
        selector that walks `Invoice.subscription.user_id` in one statement first.
        """
        customer_id, subscription_id, warehouse_id, sku_id = (
            self._somewhere_to_order_from()
        )
        invoice_id = self._an_invoice_of(subscription_id)
        order_id = self._place(
            reference="DJ-ATTACH",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            units=2,
        )

        billed = self.client.post(
            f"/orders/operate/{order_id}/attach/", {"invoice": invoice_id}
        )

        self.assertEqual(billed.status_code, 302)
        self.assertEqual(self._state_of(order_id), OrderState.INVOICED)

    def test_billing_against_an_invoice_that_is_not_there_is_a_404(self) -> None:
        """A stale id from a form is a 404 from the use case, not a foreign key error in the commit.

        The invoice is looked up rather than trusted, which is the difference between a page that
        can say "that invoice is gone" and one that hands the reader a driver message.
        """
        customer_id, _, warehouse_id, sku_id = self._somewhere_to_order_from()
        order_id = self._place(
            reference="DJ-ATTACH-GHOST",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            units=1,
        )

        billed = self.client.post(
            f"/orders/operate/{order_id}/attach/", {"invoice": 999999}
        )

        self.assertEqual(billed.status_code, 404)
        self.assertEqual(self._state_of(order_id), OrderState.DRAFT)

    def test_cancelling_a_reserved_order_gives_the_units_back(self) -> None:
        """A cancellation is a STATE and not a delete, and the hold it was carrying is released."""
        customer_id, _, warehouse_id, sku_id = self._somewhere_to_order_from()
        order_id = self._place(
            reference="DJ-STOP",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            units=7,
        )
        before = self._levels(warehouse_id, sku_id)
        self.client.post(f"/orders/operate/{order_id}/reserve/")
        self.assertEqual(self._levels(warehouse_id, sku_id), (before[0], before[1] + 7))

        cancelled = self.client.post(f"/orders/operate/{order_id}/cancel/")

        self.assertEqual(cancelled.status_code, 302)
        self.assertEqual(self._state_of(order_id), OrderState.CANCELLED)
        self.assertEqual(self._levels(warehouse_id, sku_id), before)

    def test_an_operation_that_is_not_offered_is_not_reachable(self) -> None:
        """The page prints the reason instead of the button, and the route refuses the same thing.

        Both halves matter and they are not the same check. The missing button is what a person sees;
        the 409 is what happens to the person who kept the URL, went back, or pressed twice.
        """
        order_id = self._an_order_in(OrderState.SETTLED)

        page = self._html(f"/orders/operate/{order_id}/")
        self.assertNotIn("Reserve the units", page)
        self.assertIn("Only a draft order can be reserved", page)

        refused = self.client.post(f"/orders/operate/{order_id}/reserve/")

        self.assertEqual(refused.status_code, 409)
        self.assertIn("The reservation was refused", refused.content.decode())
        self.assertEqual(self._state_of(order_id), OrderState.SETTLED)

    def test_an_operation_is_a_post_and_a_get_does_nothing(self) -> None:
        """`require_POST`: a crawler, a prefetch or a back button must not be able to reserve an order."""
        order_id = self._an_order_in(OrderState.DRAFT)

        self.assertEqual(
            self.client.get(f"/orders/operate/{order_id}/reserve/").status_code, 405
        )
        self.assertEqual(self._state_of(order_id), OrderState.DRAFT)

    def test_settling_without_naming_a_subscription_says_so(self) -> None:
        """`settle` bills against a subscription, so a form that names none is answered before the call."""
        customer_id, _, warehouse_id, sku_id = self._somewhere_to_order_from()
        order_id = self._place(
            reference="DJ-NOSUB",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
        )
        self.client.post(f"/orders/operate/{order_id}/reserve/")

        refused = self.client.post(f"/orders/operate/{order_id}/settle/", {})

        self.assertEqual(refused.status_code, 200)
        self.assertIn("issued against a subscription", refused.content.decode())
        self.assertEqual(self._state_of(order_id), OrderState.RESERVED)

    # --- the rule that only a differently configured server would show --------------------------

    def test_the_operation_is_handed_a_transaction_of_its_own(self) -> None:
        """THE GUARD. Delete a `session.rollback()` from `views.py` and this test is what goes red.

        The three operations open by DECLARING their isolation level, which is only valid as the
        first statement of a transaction. On a stock Postgres a handler that read first gets away
        with it, because the statement is refused only when it would CHANGE the level and the level
        it asks for is already the one in force — so the operation quietly stops declaring anything
        and starts inheriting whatever the connection had.

        This test hands the request a connection that HAD something else, which is what a server with
        `default_transaction_isolation` set — or MySQL, whose default is `REPEATABLE READ` — hands
        over on every request. The session is poisoned at the one seam the whole demo goes through,
        the middleware that opens it, so nothing about the view has to be arranged for.

        With the `rollback` in place the operation gets a clean transaction and answers 302. Without
        it, Postgres raises `ActiveSqlTransaction` from three layers below the handler and the demo
        500s — which is the LOUD version of a bug that is silent where it gets written.
        """
        customer_id, _, warehouse_id, sku_id = self._somewhere_to_order_from()
        order_id = self._place(
            reference="DJ-ISO",
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
        )
        opened = middleware.django_session

        def already_reading() -> SnakeSession:
            """The real request session, put at another level and made to read, before the view runs."""
            session = opened()
            session.set_isolation(SnakeIsolation.REPEATABLE_READ)
            session.first(SnakeQuery(Order).filter(Order.id == order_id))
            return session

        with patch.object(middleware, "django_session", already_reading):
            reserved = self.client.post(f"/orders/operate/{order_id}/reserve/")

        self.assertEqual(reserved.status_code, 302)
        self.assertEqual(self._state_of(order_id), OrderState.RESERVED)

    # --- the shell --------------------------------------------------------------------------------

    def test_every_page_carries_the_sidebar_and_it_shows_orders(self) -> None:
        """The context processor is what makes this true of pages no view of ours remembered."""
        order_id = self._an_order_in(OrderState.DRAFT)
        pages = (
            "/orders/list/",
            "/orders/create/",
            "/orders/operate/",
            f"/orders/detail/{order_id}/",
            f"/orders/update/{order_id}/",
            f"/orders/delete/{order_id}/",
            f"/orders/operate/{order_id}/",
        )

        for url in pages:
            html = self._html(url)
            self.assertIn('<nav class="sidebar" aria-label="Domains">', html)
            self.assertIn('href="/orders/list/"', html)
            self.assertIn('href="/orders/operate/"', html)
            self.assertIn("Reserve / settle / cancel", html)

    def test_the_sidebar_marks_the_orders_page_you_are_on(self) -> None:
        """`aria-current` rides on the link of the route being served, and on no other."""
        listing = self._html("/orders/list/")
        self.assertIn('href="/orders/list/" aria-current="page"', listing)
        self.assertNotIn('href="/orders/operate/" aria-current="page"', listing)

        chooser = self._html("/orders/operate/")
        self.assertIn('href="/orders/operate/" aria-current="page"', chooser)
        self.assertNotIn('href="/orders/list/" aria-current="page"', chooser)


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"])
class OrdersReportAndExportTests(SimpleTestCase):
    """The report and the export, which are the two pages phase 4 added to this domain.

    The report is an ordinary page and is asserted like one. The export is not: what makes it worth
    having is invisible in its answer, so the test that matters here measures how many rows the
    CURSOR consumed while only part of the file had been read.

    `SimpleTestCase`: the business data does NOT touch Django's ORM; SnakeORM carries it.
    """

    databases: set[str] | Literal["__all__"] = set()

    def setUp(self) -> None:
        """Leaves the SnakeORM database in its seeded state before each test."""
        seed.reset_and_seed()
        self.client = Client()

    # --- helpers ---------------------------------------------------------------------------------

    def _html(self, url: str, status: int = 200) -> str:
        """The decoded body of a GET, having checked the status first (a 500 is not a page)."""
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return response.content.decode()

    def _csv(self, url: str) -> list[list[str]]:
        """The WHOLE export, parsed. Only for the tests about content; never for the ones about shape.

        Draining the stream is exactly what a view must not do, and it is right in a test asking what
        the file SAYS. The test that asks whether it streams does the opposite and stops at three.
        """
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        # `assertIsInstance` does not narrow; the `assert` does, and it also states the premise
        # these tests rest on: the export ANSWERS A STREAM, not a body built up front.
        assert isinstance(response, StreamingHttpResponse)
        body = response.getvalue().decode()
        return list(csv.reader(body.splitlines()))

    # --- the report -------------------------------------------------------------------------------

    def test_the_report_renders_its_five_answers_with_real_figures(self) -> None:
        """Every section is on the page, and none of them fell back to its empty row."""
        html = self._html("/orders/report/")

        self.assertIn('aria-label="Customer roll call"', html)
        self.assertIn('aria-label="Repeat customers"', html)
        self.assertIn('aria-label="Orders by state"', html)
        self.assertIn('aria-label="Recent orders in sequence"', html)
        self.assertIn('aria-label="Highlighted orders"', html)
        self.assertNotIn("&mdash; no orders yet &mdash;", html)
        self.assertNotIn("&mdash; nobody has signed up &mdash;", html)

    def test_the_report_says_which_path_the_compound_took(self) -> None:
        """`union_supported` is the one figure on the page that depends on the ENGINE, so it is said.

        On Postgres and MySQL the highlights are ONE compound whose branches each keep their own
        `LIMIT` inside parentheses; SQLite answers `Cap.PARENTHESISED_COMPOUND` with `Nope` and the
        query falls back to two statements folded in Python. Both are correct and they cost different
        round trips, and a demo read as documentation has to name which one ran rather than print the
        same sentence whatever happened. The test asserts the page said ONE of the two and not both,
        which is what a template with the branches crossed would produce.
        """
        html = self._html("/orders/report/")

        compound = "This engine took the compound path" in html
        fallback = "fell back to TWO statements" in html
        self.assertNotEqual(
            compound, fallback, "the page claimed both paths, or neither"
        )

    def test_the_report_shows_the_window_position_of_recent_orders(self) -> None:
        """`nth_for_customer` is the number no other page in the demo can show, so it has a column."""
        html = self._html("/orders/report/")

        self.assertIn("Nth for them", html)
        self.assertIn(
            "row_number() over (partition by customer order by placed_at)", html
        )

    # --- the export -------------------------------------------------------------------------------

    def test_the_export_is_a_csv_download_and_not_a_page(self) -> None:
        """`text/csv`, the filename the shared layer chose, and no HTML anywhere near it."""
        response = self.client.get("/orders/export/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertEqual(
            response["Content-Disposition"], 'attachment; filename="order-lines.csv"'
        )
        response.close()

    def test_the_export_writes_a_header_and_real_rows(self) -> None:
        """The columns are the contract, and the line's composite key is in it in both halves.

        `line_total` is on the file because the multiplication was done in the view model: a formula
        left to whoever opens the spreadsheet is an arithmetic done two ways.
        """
        rows = self._csv("/orders/export/")

        self.assertEqual(
            rows[0],
            [
                "order_id",
                "reference",
                "state",
                "customer",
                "warehouse_code",
                "sku_id",
                "sku_name",
                "quantity",
                "unit_price",
                "line_total",
                "placed_at",
            ],
        )
        self.assertGreater(len(rows), 1, "the export carried a header and no lines")
        for row in rows[1:]:
            self.assertEqual(len(row), len(rows[0]), row)
            self.assertTrue(row[3], "the customer was not resolved")
            self.assertTrue(row[6], "the SKU name was not resolved")

    def test_the_export_narrows_to_one_state(self) -> None:
        """`?state=` filters the QUERY. A line of another state must never leave the database."""
        cancelled = self._csv("/orders/export/?state=cancelled")
        everything = self._csv("/orders/export/")

        self.assertGreater(len(cancelled), 1)
        self.assertLess(len(cancelled), len(everything))
        for row in cancelled[1:]:
            self.assertEqual(row[2], OrderState.CANCELLED.value)

    def test_a_state_nobody_has_heard_of_exports_everything(self) -> None:
        """`parse_state` turns a typo into NO filter, and the export inherits that decision whole.

        The alternative was a 500 on a hand-edited query string, and the reason it is not re-derived
        here is that a second `try/except` in the view would be the same decision living twice, on
        two demos.
        """
        typo = self._csv("/orders/export/?state=nonsense")
        everything = self._csv("/orders/export/")

        self.assertEqual(len(typo), len(everything))

    def test_reading_part_of_the_export_reads_only_that_part(self) -> None:
        """THE test of this class, and the one the shared suite structurally cannot write.

        `shared/tests/test_exports_stream.py` proves the VIEW MODEL is lazy and never looks at a
        handler, so a `list()` in the view would keep all of it green while the page went back to
        holding every order line in memory before writing the first byte. This one watches the VIEW:
        four chunks (the header and three lines), then the download is torn down the way an abandoned
        one is, and what the CURSOR consumed is read out of the collector.

        IT ALSO PROVES THE SESSION OUTLIVED THE REQUEST. `SnakeSessionMiddleware` commits and CLOSES
        `request.snake_session` the moment the view returns, and every byte below is read after that,
        outside the request entirely. A view streaming off the request's session would raise here
        rather than hand over rows; `apps/exports.py` opens one of its own and closes it in the
        `finally` this test triggers by calling `response.close()`.
        """
        response = self.client.get("/orders/export/")
        self.assertTrue(response.streaming)
        assert isinstance(response, StreamingHttpResponse)

        with capture_queries() as collector:
            stream = iter(response)
            chunks = [next(stream) for _ in range(4)]
            response.close()

        report = collector.report()
        reads = [record for record in report.records if record.rows]
        self.assertEqual(len(chunks), 4)
        self.assertEqual(len(reads), 1, report.to_text())
        self.assertEqual(
            reads[0].rows,
            3,
            f"the cursor consumed {reads[0].rows} rows for a three-row read: the view "
            f"materialised the export instead of streaming it.",
        )

    # --- the shell --------------------------------------------------------------------------------

    def test_the_report_carries_the_sidebar_and_the_export_carries_no_shell(
        self,
    ) -> None:
        """The report is a page and gets the shell; the export is a file and must NOT be given one.

        A CSV that arrived wrapped in a layout would be a download nobody can open, and the mistake
        is one `{% extends %}` away from happening.
        """
        html = self._html("/orders/report/")
        self.assertIn('<nav class="sidebar" aria-label="Domains">', html)
        self.assertIn('href="/orders/report/" aria-current="page"', html)
        self.assertIn('href="/orders/export/"', html)

        response = self.client.get("/orders/export/")
        assert isinstance(response, StreamingHttpResponse)
        body = response.getvalue().decode()
        self.assertNotIn("<nav", body)
        self.assertNotIn("<!doctype html>", body)
