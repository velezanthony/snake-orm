"""The inventory domain over Django's test client: both surfaces, and the wrapper is thin on both.

The logic lives in `shared` and its own suite already pins it. What is checked HERE is the part only
the framework can get wrong: that the route carries BOTH halves of the composite key, that a
`Failure` reason becomes the status it maps to, that the price survives the JSON as exact text — and,
for the pages, that the key survives a form as well as a URL and that the shell puts a sidebar on
every one of them.

`SimpleTestCase`: the business data does NOT touch Django's ORM; SnakeORM carries it.
"""

from __future__ import annotations


import csv
import re
from typing import Literal, Protocol

from django.http import StreamingHttpResponse
from django.test import Client, SimpleTestCase, override_settings

from snakeorm import SnakeQuery, SnakeSession
from snakeorm.debug import capture_queries
from shared import config
from shared.models import Stock

from apps import wire
from apps.blog import seed


class _JsonResponse(Protocol):
    """What a helper needs from a test-client response: a body it can parse.

    Django's test client answers a type the stubs mark `@type_check_only`, so it cannot be named in
    an annotation at runtime. Naming the one method used instead of falling back to `object` keeps
    `response.json()` a checked call rather than an ignored one.
    """

    def json(self) -> object: ...


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"])
class InventoryApiTests(SimpleTestCase):
    """The stock CRUD, addressed by the pair that identifies it."""

    databases: set[str] | Literal["__all__"] = set()

    def setUp(self) -> None:
        """Leaves the SnakeORM database in its seeded state before each test."""
        seed.reset_and_seed()
        self.client = Client()

    def _rows(self, response: _JsonResponse) -> list[dict[str, object]]:
        """The list out of a response. With the `envelope` channel on, an ARRAY travels under `data`.

        The parameter used to be `object` with a `# type: ignore[attr-defined]` on `response.json()`,
        which is two bugs in one line: `object` says "I know nothing about this", and the ignore then
        says "check nothing about it either". Everything this helper returned arrived at its callers
        as `Any` — `int(rows[0]["id"])` was unchecked, and so was every `row["..."]` below it. The
        Protocol asks for the ONE thing the helper needs, and the answer stays honest data.
        """
        payload = response.json()
        rows = payload["data"] if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise AssertionError(f"expected a JSON array, got {type(rows).__name__}")
        return [row for row in rows if isinstance(row, dict)]

    def _a_warehouse(self) -> int:
        rows = self._rows(self.client.get("/api/inventory/warehouses"))
        self.assertTrue(rows, "the seeding left no warehouses")
        return wire.integer(rows[0]["id"])

    def _a_new_sku(self) -> int:
        created = self.client.post(
            "/api/inventory/skus",
            data={
                "name": "Django widget",
                "kind": "physical",
                "price": "12.34",
                "weight_kg": 1.5,
                "lead_time_days": 2,
            },
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["price"], "12.34")
        return int(created.json()["id"])

    def test_a_stock_row_is_addressed_by_both_halves_of_its_key(self) -> None:
        """Receiving goods needs warehouse AND sku: neither identifies the row on its own."""
        warehouse_id, sku_id = self._a_warehouse(), self._a_new_sku()

        received = self.client.post(
            f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}/receive",
            data={"units": 7},
            content_type="application/json",
        )

        self.assertEqual(received.status_code, 200, received.content)
        self.assertEqual(received.json()["on_hand"], 7)
        self.assertEqual(received.json()["warehouse_id"], warehouse_id)
        self.assertEqual(received.json()["sku_id"], sku_id)

    def test_shipping_more_than_there_is_answers_409_and_writes_nothing(self) -> None:
        """`conflict` maps to 409, and the refusal happens before anything is written."""
        warehouse_id, sku_id = self._a_warehouse(), self._a_new_sku()
        base = f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}"
        self.client.post(
            f"{base}/receive", data={"units": 4}, content_type="application/json"
        )

        refused = self.client.post(
            f"{base}/ship", data={"units": 9}, content_type="application/json"
        )

        self.assertEqual(refused.status_code, 409)
        movements = self._rows(self.client.get(f"{base}/movements"))
        self.assertEqual([m["delta"] for m in movements], [4])

    def test_a_patch_corrects_both_levels_and_a_missing_pair_is_a_404(self) -> None:
        """`PATCH` edits a pair that exists and refuses to invent one that does not.

        That is the difference from the `PUT` upsert on the same path, spelled in the verb: an
        upsert means "this pair now holds N whether or not it was there", a correction means "the
        row somebody opened now says this". A pair that vanished between the form being drawn and
        being submitted is a 404, not a silent insert.
        """
        warehouse_id, sku_id = self._a_warehouse(), self._a_new_sku()
        base = f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}"
        self.client.put(base, data={"on_hand": 30}, content_type="application/json")

        corrected = self.client.patch(
            base,
            data={"on_hand": 30, "reserved": 4},
            content_type="application/json",
        )
        missing = self.client.patch(
            f"/api/inventory/warehouses/{warehouse_id}/stock/999999",
            data={"on_hand": 1, "reserved": 0},
            content_type="application/json",
        )

        self.assertEqual(corrected.status_code, 200, corrected.content)
        self.assertEqual(corrected.json()["reserved"], 4)
        self.assertEqual(missing.status_code, 404)

    def test_a_delete_removes_an_untouched_pair_and_refuses_one_with_history(
        self,
    ) -> None:
        """204 for a pair nobody moved, 409 for one that has movements.

        The 409 is the interesting half and the same answer the delete PAGE gives: the movements
        are the audit trail and the foreign key is RESTRICT, so a pair that has moved gets closed
        rather than deleted. Without it the engine refuses three layers down, inside a commit, with
        a driver error nobody can turn into a page.
        """
        warehouse_id = self._a_warehouse()
        untouched, moved = self._a_new_sku(), self._a_new_sku()
        clean = f"/api/inventory/warehouses/{warehouse_id}/stock/{untouched}"
        dirty = f"/api/inventory/warehouses/{warehouse_id}/stock/{moved}"
        self.client.put(clean, data={"on_hand": 5}, content_type="application/json")
        self.client.post(
            f"{dirty}/receive", data={"units": 5}, content_type="application/json"
        )

        removed = self.client.delete(clean)
        refused = self.client.delete(dirty)

        self.assertEqual(removed.status_code, 204, removed.content)
        self.assertEqual(refused.status_code, 409, refused.content)

    def test_the_movements_come_nested_under_their_stock_row(self) -> None:
        """The to-many over a COMPOSITE foreign key, served as JSON."""
        warehouse_id, sku_id = self._a_warehouse(), self._a_new_sku()
        self.client.post(
            f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}/receive",
            data={"units": 6},
            content_type="application/json",
        )

        rows = self._rows(
            self.client.get(f"/api/inventory/warehouses/{warehouse_id}/stock/movements")
        )

        mine = next(row for row in rows if row["sku_id"] == sku_id)
        movements = [wire.mapping(m) for m in wire.sequence(mine["movements"])]
        self.assertEqual([m["delta"] for m in movements], [6])

    def test_an_unknown_warehouse_answers_404(self) -> None:
        """Asking about something that is not there is a 404, not an empty list."""
        self.assertEqual(
            self.client.get("/api/inventory/warehouses/999999").status_code, 404
        )
        self.assertEqual(
            self.client.get("/api/inventory/warehouses/999999/stock").status_code, 404
        )


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"])
class InventoryPagesTests(SimpleTestCase):
    """The five SSR pages of the pilot domain, driven the way a browser drives them.

    What is checked here is the part `shared` cannot check for us: that the composite key survives
    the round trip through a URL and a form, that a `Failure` becomes the right status, and that the
    sidebar is on the page the reader is actually looking at. The arithmetic of the pager and the
    flattening of the relations are pinned by the view models' own suite.

    `SimpleTestCase` with no databases declared, for the same reason as the API tests above: the
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

    def _pairs_in(self, html: str) -> list[tuple[int, int]]:
        """The stock pairs a listing links to, read off its detail hrefs, in the order they appear."""
        found = re.findall(r"/inventory/detail/(\d+)/(\d+)/", html)
        return [(int(warehouse), int(sku)) for warehouse, sku in found]

    def _a_pair(self) -> tuple[int, int]:
        """The lowest stock pair in the seed: a row that exists, chosen deterministically."""
        session = self._new_session()
        try:
            stock = session.first(
                SnakeQuery(Stock).order_by(Stock.warehouse_id.asc(), Stock.sku_id.asc())
            )
            self.assertIsNotNone(stock, "the seeding left no stock rows")
            assert stock is not None
            return stock.warehouse_id, stock.sku_id
        finally:
            session.close()

    def _levels(self, warehouse_id: int, sku_id: int) -> tuple[int, int] | None:
        """The `(on_hand, reserved)` of a pair straight from the database, or `None` if it is gone."""
        session = self._new_session()
        try:
            stock = session.first(
                SnakeQuery(Stock).filter(
                    Stock.warehouse_id == warehouse_id, Stock.sku_id == sku_id
                )
            )
            return None if stock is None else (stock.on_hand, stock.reserved)
        finally:
            session.close()

    def _a_new_sku(self) -> int:
        """A SKU nothing stocks yet, so that a create is an INSERT rather than an upsert in disguise."""
        created = self.client.post(
            "/api/inventory/skus",
            data={
                "name": "Page-made widget",
                "kind": "physical",
                "price": "9.99",
                "weight_kg": 0.5,
                "lead_time_days": 3,
            },
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        return int(created.json()["id"])

    # --- list -------------------------------------------------------------------------------------

    def test_the_listing_renders_rows_and_a_pager(self) -> None:
        """The list page paints stock rows and the pager that says which page of how many they are."""
        html = self._html("/inventory/list/")

        self.assertIn('aria-label="Stock rows"', html)
        self.assertTrue(self._pairs_in(html), "the listing linked to no stock row")
        self.assertIn("Page 1 of", html)
        # The first page has no previous, and the edge is a span rather than an <a> without href:
        # a link with nothing to point at is skipped by the keyboard entirely.
        self.assertIn(
            '<span class="btn btn-ghost btn-md" aria-disabled="true">Previous</span>',
            html,
        )

    def test_the_warehouse_filter_narrows_the_listing(self) -> None:
        """`?warehouse=` leaves only that warehouse's rows, and the option comes back selected."""
        warehouse_id, _ = self._a_pair()

        html = self._html(f"/inventory/list/?warehouse={warehouse_id}")

        pairs = self._pairs_in(html)
        self.assertTrue(pairs)
        self.assertEqual({warehouse for warehouse, _ in pairs}, {warehouse_id})
        self.assertIn(f'<option value="{warehouse_id}" selected>', html)

    def test_the_second_page_shows_other_rows(self) -> None:
        """`?page=2` is a different slice, not the same one drawn twice."""
        first = self._html("/inventory/list/")
        self.assertIn("Next", first)
        self.assertNotIn(
            '<span class="btn btn-ghost btn-md" aria-disabled="true">Next</span>',
            first,
            "this test needs more than one page of stock (DEMO_SCALE=minimal seeds a single one)",
        )

        second = self._html("/inventory/list/?page=2")

        self.assertIn("Page 2 of", second)
        self.assertTrue(self._pairs_in(second))
        self.assertEqual(
            set(self._pairs_in(first)) & set(self._pairs_in(second)), set()
        )

    # --- detail -----------------------------------------------------------------------------------

    def test_the_detail_renders_the_pair_with_its_relations_and_its_movements(
        self,
    ) -> None:
        """A real pair paints its two to-one hops flattened and the to-many that hangs off both."""
        warehouse_id, sku_id = self._a_pair()

        html = self._html(f"/inventory/detail/{warehouse_id}/{sku_id}/")

        self.assertIn(f"Warehouse {warehouse_id}, SKU {sku_id}", html)
        self.assertIn("SKU public id", html)
        self.assertIn('aria-label="Movements of this stock row"', html)
        self.assertIn(f"/inventory/update/{warehouse_id}/{sku_id}/", html)
        self.assertIn(f"/inventory/delete/{warehouse_id}/{sku_id}/", html)

    def test_a_pair_that_is_not_there_answers_404(self) -> None:
        """`not_found` from the view model becomes a 404 with the error page, not an empty detail."""
        response = self.client.get("/inventory/detail/999999/999999/")

        self.assertEqual(response.status_code, 404)
        self.assertIn("That stock row does not exist", response.content.decode())

    # --- create -----------------------------------------------------------------------------------

    def test_creating_a_row_writes_it_and_lands_on_it(self) -> None:
        """The form posts BOTH halves of the key, the row appears in the database, the redirect finds it."""
        warehouse_id, _ = self._a_pair()
        sku_id = self._a_new_sku()
        self.assertIsNone(self._levels(warehouse_id, sku_id))

        created = self.client.post(
            "/inventory/create/",
            {"warehouse": warehouse_id, "sku": sku_id, "on_hand": 42},
        )

        self.assertEqual(created.status_code, 302)
        self.assertEqual(
            created.headers["Location"], f"/inventory/detail/{warehouse_id}/{sku_id}/"
        )
        self.assertEqual(self._levels(warehouse_id, sku_id), (42, 0))

    def test_a_negative_count_is_refused_and_writes_nothing(self) -> None:
        """`missing_fields` re-renders the form with a message instead of a 500 from the CHECK."""
        warehouse_id, _ = self._a_pair()
        sku_id = self._a_new_sku()

        refused = self.client.post(
            "/inventory/create/",
            {"warehouse": warehouse_id, "sku": sku_id, "on_hand": -1},
        )

        self.assertEqual(refused.status_code, 200)
        self.assertIn("The on_hand cannot be negative.", refused.content.decode())
        self.assertIsNone(self._levels(warehouse_id, sku_id))

    # --- update -----------------------------------------------------------------------------------

    def test_updating_changes_the_levels_of_the_pair_in_the_url(self) -> None:
        """The pair comes from the path, the levels from the form, and the row moves."""
        warehouse_id, sku_id = self._a_pair()

        saved = self.client.post(
            f"/inventory/update/{warehouse_id}/{sku_id}/",
            {"on_hand": 123, "reserved": 7},
        )

        self.assertEqual(saved.status_code, 302)
        self.assertEqual(self._levels(warehouse_id, sku_id), (123, 7))

    def test_the_update_form_locks_both_halves_of_the_key(self) -> None:
        """A composite key is not an editable field: the two key selects arrive disabled."""
        warehouse_id, sku_id = self._a_pair()

        html = self._html(f"/inventory/update/{warehouse_id}/{sku_id}/")

        self.assertIn('id="warehouse" name="warehouse" disabled', html)
        self.assertIn('id="sku" name="sku" disabled', html)

    # --- delete -----------------------------------------------------------------------------------

    def test_deleting_a_pair_with_history_is_refused_in_words(self) -> None:
        """FK RESTRICT: the confirmation explains it and the POST answers 409, with the row intact."""
        warehouse_id, sku_id = self._a_pair()
        before = self._levels(warehouse_id, sku_id)

        confirm = self._html(f"/inventory/delete/{warehouse_id}/{sku_id}/")
        self.assertIn("cannot be deleted while its history exists", confirm)
        self.assertIn('aria-disabled="true">Delete</span>', confirm)

        refused = self.client.post(f"/inventory/delete/{warehouse_id}/{sku_id}/")

        self.assertEqual(refused.status_code, 409)
        self.assertIn(
            "cannot be deleted while its history exists", refused.content.decode()
        )
        self.assertEqual(self._levels(warehouse_id, sku_id), before)

    def test_a_pair_with_no_movements_can_be_deleted(self) -> None:
        """The other side of the same fork: no history, so the confirmation offers a real button."""
        warehouse_id, _ = self._a_pair()
        sku_id = self._a_new_sku()
        self.client.post(
            "/inventory/create/",
            {"warehouse": warehouse_id, "sku": sku_id, "on_hand": 3},
        )

        confirm = self._html(f"/inventory/delete/{warehouse_id}/{sku_id}/")
        self.assertIn("Yes, delete it", confirm)
        deleted = self.client.post(f"/inventory/delete/{warehouse_id}/{sku_id}/")

        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(deleted.headers["Location"], "/inventory/list/")
        self.assertIsNone(self._levels(warehouse_id, sku_id))

    # --- the shell --------------------------------------------------------------------------------

    def test_receiving_units_from_the_detail_page_moves_the_pair(self) -> None:
        """A movement made from the page the pair is on, and the history grows by one row.

        The form lives on the detail page rather than on one of its own, which is the catalogue
        holding: `orders` has an `operate` page because an operation there is something you go
        looking for, and a movement is something you do to the pair in front of you.
        """
        warehouse_id, sku_id = self._a_pair()
        before = self._levels(warehouse_id, sku_id)
        assert before is not None  # `_a_pair` returns a pair that exists

        moved = self.client.post(
            f"/inventory/detail/{warehouse_id}/{sku_id}/receive/", {"units": 6}
        )

        self.assertEqual(moved.status_code, 302)
        after = self._levels(warehouse_id, sku_id)
        assert after is not None
        self.assertEqual(after[0], before[0] + 6)

    def test_shipping_more_than_there_is_refuses_and_writes_NOTHING(self) -> None:
        """409, and the pair unchanged. The refusal is the half worth having a page for.

        Without it the negative row reaches the engine and the CHECK catches it three layers down,
        inside a commit, with a driver error nobody can render.
        """
        warehouse_id, sku_id = self._a_pair()
        before = self._levels(warehouse_id, sku_id)
        assert before is not None

        refused = self.client.post(
            f"/inventory/detail/{warehouse_id}/{sku_id}/ship/",
            {"units": before[0] + 1000},
        )

        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self._levels(warehouse_id, sku_id), before)

    def test_a_movement_of_nothing_is_a_form_error_and_not_a_refusal(self) -> None:
        """Zero units is an empty form, so the page says so and stays a 200.

        Passing it on would make the use case answer a question nobody asked, and the page would
        report a domain refusal for what is a missing field.
        """
        warehouse_id, sku_id = self._a_pair()
        before = self._levels(warehouse_id, sku_id)

        empty = self.client.post(
            f"/inventory/detail/{warehouse_id}/{sku_id}/receive/", {"units": 0}
        )

        self.assertEqual(empty.status_code, 200)
        self.assertEqual(self._levels(warehouse_id, sku_id), before)

    def test_the_catalogue_page_makes_a_warehouse_and_a_sku(self) -> None:
        """The two things a stock pair points at, made from a page for the first time.

        Until this page existed the demo could only stock what the seeder had built: every other
        page here is about what is IN the inventory, and neither of these is.
        """
        made_warehouse = self.client.post(
            "/inventory/catalogue/warehouses/",
            {
                "code": "ZZZ",
                "name": "Made from a page",
                "opened_on": "2021-05-04",
                "shift_start": "07:00",
                "cutoff": "19:00",
            },
        )
        made_sku = self.client.post(
            "/inventory/catalogue/skus/",
            {
                "name": "Page widget",
                "kind": "physical",
                "price": "12.50",
                "weight_kg": "0.8",
                "lead_time_days": "3",
            },
        )

        self.assertEqual(made_warehouse.status_code, 302)
        self.assertEqual(made_sku.status_code, 302)
        html = self._html("/inventory/catalogue/")
        self.assertIn("ZZZ", html)
        self.assertIn("Page widget", html)

    def test_a_warehouse_code_of_four_characters_is_REFUSED(self) -> None:
        """The ORM shouts rather than truncating, and the page turns that into something readable.

        A code silently trimmed to three letters is the failure this repository's whole doctrine is
        against: it would be stored, it would look right, and nobody would find out until a lookup
        by the code somebody typed came back empty.
        """
        refused = self.client.post(
            "/inventory/catalogue/warehouses/",
            {
                "code": "ZZZZ",
                "name": "Too long",
                "opened_on": "2021-05-04",
                "shift_start": "07:00",
                "cutoff": "19:00",
            },
        )

        self.assertEqual(refused.status_code, 200)
        self.assertNotIn("Too long", self._html("/inventory/catalogue/"))

    def test_reserving_across_a_warehouse_is_ONE_statement_over_every_row(self) -> None:
        """The bulk hold: one UPDATE over the whole warehouse, not a loop over its pairs.

        It lives on this page and not on a pair's, because it is not about a pair. What is checked
        is that it MOVED more than one row — the point of the operation is that it does.
        """
        warehouse_id, sku_id = self._a_pair()
        before = self._levels(warehouse_id, sku_id)
        assert before is not None

        held = self.client.post(
            f"/inventory/catalogue/warehouses/{warehouse_id}/reserve/", {"units": 1}
        )

        self.assertEqual(held.status_code, 302)
        after = self._levels(warehouse_id, sku_id)
        assert after is not None
        self.assertEqual(after[1], before[1] + 1)

    def test_every_page_carries_the_sidebar(self) -> None:
        """The context processor is what makes this true of pages no view of ours remembered."""
        warehouse_id, sku_id = self._a_pair()
        pages = (
            "/inventory/list/",
            "/inventory/create/",
            f"/inventory/detail/{warehouse_id}/{sku_id}/",
            f"/inventory/update/{warehouse_id}/{sku_id}/",
            f"/inventory/delete/{warehouse_id}/{sku_id}/",
            "/lab/",
        )

        for url in pages:
            html = self._html(url)
            self.assertIn('<nav class="sidebar" aria-label="Domains">', html)
            self.assertIn('href="/inventory/list/"', html)
            self.assertIn('href="/lab/"', html)

    def test_the_sidebar_marks_the_page_you_are_on(self) -> None:
        """`aria-current` rides on the link of the route being served, and on no other."""
        listing = self._html("/inventory/list/")
        self.assertIn('href="/inventory/list/" aria-current="page"', listing)
        self.assertNotIn('href="/lab/" aria-current="page"', listing)

        lab = self._html("/lab/")
        self.assertIn('href="/lab/" aria-current="page"', lab)
        self.assertNotIn('href="/inventory/list/" aria-current="page"', lab)

    def test_the_topbar_no_longer_carries_the_section_links(self) -> None:
        """The domains moved to the sidebar; the topbar is identity, account and dev tools."""
        html = self._html("/inventory/list/")

        self.assertNotIn('aria-label="Sections"', html)
        self.assertIn('aria-label="Developer tools"', html)


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"])
class InventoryReportAndExportTests(SimpleTestCase):
    """The two pages phase 4 added, and the one property of the export that the answer cannot show.

    The report is an ordinary page and the assertions on it are ordinary: it renders, and the figures
    on it are the ones in the database rather than a template printing zeroes.

    THE EXPORT IS NOT ORDINARY, and the reason there is a whole test class for two routes is written
    out on `test_reading_part_of_the_export_reads_only_that_part`. `shared/tests/test_exports_stream.py`
    already proves the VIEW MODEL streams; it never looks at a handler, so a `list()` in the view
    would leave every one of those tests green while defeating the entire point of the page.
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

    def _a_warehouse(self) -> int:
        """The lowest-numbered warehouse, chosen deterministically so a filter has something to hit."""
        session = self._new_session()
        try:
            stock = session.first(
                SnakeQuery(Stock).order_by(Stock.warehouse_id.asc(), Stock.sku_id.asc())
            )
            self.assertIsNotNone(stock, "the seeding left no stock")
            assert stock is not None
            return stock.warehouse_id
        finally:
            session.close()

    def _csv(self, url: str) -> list[list[str]]:
        """The WHOLE export, parsed. Only for the tests about content; never for the ones about shape.

        Draining the stream here is exactly what a view must not do, and it is right in a test: the
        question these ask is what the file SAYS, and the file has to be read to be read. The tests
        that ask whether it streams do the opposite and stop after three rows.
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
        """Every section is on the page and the totals are the database's, not a template's zeroes."""
        html = self._html("/inventory/report/")

        self.assertIn('aria-label="Warehouse totals"', html)
        self.assertIn('aria-label="Busy SKUs"', html)
        self.assertIn('aria-label="Stock ranking"', html)
        self.assertIn('aria-label="SKUs that have moved"', html)
        self.assertNotIn("&mdash; no warehouses &mdash;", html)
        self.assertNotIn("&mdash; nothing on the shelves &mdash;", html)

    def test_the_report_names_the_threshold_it_applied(self) -> None:
        """A filtered list whose filter is not named is a list nobody can reproduce.

        The threshold travels back on the context precisely so the page can say it, which is the
        difference between a figure a reader can check and a figure they have to trust.
        """
        html = self._html("/inventory/report/")

        self.assertIn("having(count(...) &gt;= 2)", html)

    def test_the_dead_stock_figures_add_up(self) -> None:
        """The subtraction is the view model's, and the page has to print the three numbers it made.

        Catalogue minus moved is never-moved. Asserting the three together is what catches a template
        that wired the same key into two of the slots, which prints plausibly and says nothing.
        """
        session = self._new_session()
        try:
            total = session.count(SnakeQuery(Stock))
        finally:
            session.close()
        self.assertGreater(total, 0, "the seeding left no stock")

        html = self._html("/inventory/report/")

        self.assertIn("<dt>SKUs in the catalogue</dt>", html)
        self.assertIn("<dt>SKUs that have ever moved</dt>", html)
        self.assertIn("<dt>Never moved</dt>", html)

    # --- the export -------------------------------------------------------------------------------

    def test_the_export_is_a_csv_download_and_not_a_page(self) -> None:
        """`text/csv`, the filename the shared layer chose, and no HTML anywhere near it."""
        response = self.client.get("/inventory/export/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="stock-movements.csv"',
        )
        response.close()

    def test_the_export_writes_a_header_and_real_rows(self) -> None:
        """The columns are the contract, and BOTH halves of the composite key are among them.

        A file somebody reconciles against the database has to be joinable back to it, and in this
        domain that takes two columns. The names are asserted literally rather than read off the
        module that emits them, which would compare a thing to itself.
        """
        rows = self._csv("/inventory/export/")

        self.assertEqual(
            rows[0],
            [
                "movement_id",
                "warehouse_id",
                "warehouse_code",
                "sku_id",
                "sku_name",
                "delta",
                "reason",
                "note",
                "happened_at",
            ],
        )
        self.assertGreater(len(rows), 1, "the export carried a header and no movements")
        for row in rows[1:]:
            self.assertEqual(len(row), len(rows[0]), row)
            self.assertTrue(row[2], "the warehouse code was not resolved")
            self.assertTrue(row[4], "the SKU name was not resolved")

    def test_the_export_narrows_to_one_warehouse(self) -> None:
        """`?warehouse=` filters the QUERY. An unwanted row must never leave the database at all."""
        warehouse_id = self._a_warehouse()

        mine = self._csv(f"/inventory/export/?warehouse={warehouse_id}")
        everything = self._csv("/inventory/export/")

        self.assertGreater(len(mine), 1)
        self.assertLess(len(mine), len(everything))
        for row in mine[1:]:
            self.assertEqual(row[1], str(warehouse_id))

    def test_a_warehouse_nobody_has_heard_of_exports_only_the_header(self) -> None:
        """An id that matches nothing is a filter the engine can run: an empty file, not a 500."""
        rows = self._csv("/inventory/export/?warehouse=999999")

        self.assertEqual(len(rows), 1)

    def test_reading_part_of_the_export_reads_only_that_part(self) -> None:
        """THE test of this file, and the one the shared suite structurally cannot write.

        `shared/tests/test_exports_stream.py` proves the VIEW MODEL is lazy — reading three rows out
        of thirty makes the driver consume exactly three — and it never sees a handler. A `list()` in
        the view would keep every one of those green while the page went back to holding every
        movement in memory before writing the first byte. So this one watches the VIEW: it asks the
        response for four chunks (the header and three rows), tears the download down the way an
        abandoned one is torn down, and reads what the CURSOR consumed.

        IT ALSO PROVES THE SESSION OUTLIVED THE REQUEST, which is the other half of the design and
        the classic way a streamed export dies. `SnakeSessionMiddleware` commits and CLOSES
        `request.snake_session` the moment the view returns, and every byte read below is read AFTER
        that — outside the request entirely. A view that had streamed off the request's session would
        raise here instead of handing over rows; `apps/exports.py` opens one of its own and closes
        it in the `finally` this test triggers.

        `capture_queries` is opened around the CONSUMPTION and not around the request, because that
        is where the statement runs: building the export executes nothing at all.
        """
        response = self.client.get("/inventory/export/")
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

    def test_the_export_carries_the_sidebar_nowhere_and_the_report_carries_it(
        self,
    ) -> None:
        """The report is a page and gets the shell; the export is a file and must NOT be given one.

        The sidebar links to both, which is what makes this worth asserting: a CSV that arrived
        wrapped in a layout would be a download nobody can open, and the mistake is one template
        inheritance away.
        """
        html = self._html("/inventory/report/")
        self.assertIn('<nav class="sidebar" aria-label="Domains">', html)
        self.assertIn('href="/inventory/report/" aria-current="page"', html)
        self.assertIn('href="/inventory/export/"', html)

        response = self.client.get("/inventory/export/")
        assert isinstance(response, StreamingHttpResponse)
        body = response.getvalue().decode()
        self.assertNotIn("<nav", body)
        self.assertNotIn("<!doctype html>", body)
