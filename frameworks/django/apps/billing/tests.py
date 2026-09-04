"""The billing pages over Django's test client: the three the money gets, and the two it does not.

The logic lives in `shared` and its own suite already pins it — the pager's arithmetic, the three
flattened to-one hops per row, the sum of the payments against the amount owed. What is checked HERE
is the part only the framework can get wrong: that a route carries what the page needs, that
`not_found` becomes the status it maps to, that the filter narrows what the DATABASE returned rather
than what the template printed, and that the shell puts a sidebar on every one of these pages.

AND ONE THING THAT IS AN ABSENCE. `test_the_domain_offers_no_way_to_write_an_invoice` fails if
somebody adds a create, an update or a delete here. That is not tidiness: an invoice is raised by
`settle` over in orders and paid by `pay_invoice`, both of them operations with a transaction around
them, and a form that let somebody retype an amount would be a demo of the one thing accounting
software must never offer. `shared/tests/test_nav.py` asserts the same absence in the catalogue; this
asserts it in the router, which is where a page would actually appear.

`SimpleTestCase`: the business data does NOT touch Django's ORM; SnakeORM carries it.
"""

from __future__ import annotations


import re
from typing import Literal

from django.test import Client, SimpleTestCase, override_settings
from django.urls import NoReverseMatch, reverse

from snakeorm import SnakeQuery, SnakeSession
from shared import config
from shared.models import Invoice, Payment

from apps.blog import seed


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"])
class BillingPagesTests(SimpleTestCase):
    """The three pages of the read-only money domain: list, detail and report."""

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
        """The invoices a listing links to, read off its detail hrefs, in the order they appear."""
        return [int(found) for found in re.findall(r"/billing/detail/(\d+)/", html)]

    def _settlement_of(self, invoice_ids: list[int]) -> set[bool]:
        """Whether those invoices are settled, STRAIGHT FROM THE DATABASE, not off the badges.

        Reading the filter's effect out of the HTML would prove the template printed what it was
        handed, which is not the question: what the filter has to be right about is which rows came
        back at all.
        """
        session = self._new_session()
        try:
            return {
                invoice.paid
                for invoice in session.all(
                    SnakeQuery(Invoice).filter(Invoice.id.in_(invoice_ids))
                )
            }
        finally:
            session.close()

    def _an_invoice(self, *, paid: bool) -> int:
        """The lowest-numbered seeded invoice in that settlement state, chosen deterministically."""
        session = self._new_session()
        try:
            invoice = session.first(
                SnakeQuery(Invoice)
                .filter(Invoice.paid == paid)
                .order_by(Invoice.id.asc())
            )
            self.assertIsNotNone(invoice, f"the seeding left no paid={paid} invoice")
            assert invoice is not None
            return invoice.id
        finally:
            session.close()

    def _an_invoice_with_payments(self) -> int:
        """An invoice that HAS payments against it, found from the payment side rather than assumed.

        Asked for from the invoice side —"the first settled one"— this comes back as an invoice with
        an empty payments table often enough to matter: the `paid` flag and the payments are two
        different facts and nothing in the schema ties them, which is the very thing the detail page
        exists to show. Starting from a payment guarantees the to-many has something in it.
        """
        session = self._new_session()
        try:
            payment = session.first(SnakeQuery(Payment).order_by(Payment.id.asc()))
            self.assertIsNotNone(payment, "the seeding left no payments")
            assert payment is not None
            return payment.invoice_id
        finally:
            session.close()

    # --- list -------------------------------------------------------------------------------------

    def test_the_listing_renders_rows_and_a_pager(self) -> None:
        """The list page paints invoices and the pager that says which page of how many they are."""
        html = self._html("/billing/list/")

        self.assertIn('aria-label="Invoices"', html)
        self.assertTrue(self._ids_in(html), "the listing linked to no invoice")
        self.assertIn("Page 1 of", html)
        # The first page has no previous, and the edge is a span rather than an <a> without href:
        # a link with nothing to point at is skipped by the keyboard entirely.
        self.assertIn(
            '<span class="btn btn-ghost btn-md" aria-disabled="true">Previous</span>',
            html,
        )

    def test_the_row_carries_the_whole_chain_behind_the_invoice(self) -> None:
        """Customer, plan and plan price are on the row, which is the three-hop flattening working.

        A blank in any of those columns is what a template navigating `invoice.subscription.plan`
        itself would produce the day the `include` was dropped — it would keep rendering, one query
        per hop per row, and only the numbers on the panel would change. Here the names come off a
        row the view model already flattened, so a blank means the JOIN stopped happening.
        """
        html = self._html("/billing/list/")

        self.assertIn("Subscription ", html)
        self.assertIn(" per period", html)
        self.assertNotIn("<td></td>", html)

    def test_the_paid_filter_narrows_the_listing(self) -> None:
        """`?paid=paid` leaves only settled invoices, and the option comes back selected."""
        html = self._html("/billing/list/?paid=paid")

        ids = self._ids_in(html)
        self.assertTrue(ids)
        self.assertEqual(self._settlement_of(ids), {True})
        self.assertIn('<option value="paid" selected>', html)

    def test_the_open_filter_is_the_other_half_of_the_same_fork(self) -> None:
        """`?paid=open` leaves only the outstanding ones, which is the figure the report is about."""
        html = self._html("/billing/list/?paid=open")

        ids = self._ids_in(html)
        self.assertTrue(ids)
        self.assertEqual(self._settlement_of(ids), {False})
        self.assertIn('<option value="open" selected>', html)

    def test_a_filter_nobody_has_heard_of_shows_everything(self) -> None:
        """A typo in a hand-edited URL is not a 500 and not an empty table: it is no filter at all.

        `parse_paid` chose that over raising, and the reason is worth a test: `paid=maybe` cannot be
        turned into a filter at all — there is no third value of a boolean — so the alternatives were
        "show everything" and a 500 on a query string somebody mistyped.
        """
        typo = self._html("/billing/list/?paid=maybe")

        self.assertEqual(self._ids_in(typo), self._ids_in(self._html("/billing/list/")))
        self.assertIn('<option value="" selected>', typo)

    def test_the_second_page_shows_other_invoices(self) -> None:
        """`?page=2` is a different slice, not the same one drawn twice."""
        first = self._html("/billing/list/")
        self.assertNotIn(
            '<span class="btn btn-ghost btn-md" aria-disabled="true">Next</span>',
            first,
            "this test needs more than one page of invoices (DEMO_SCALE=minimal seeds a single one)",
        )

        second = self._html("/billing/list/?page=2")

        self.assertIn("Page 2 of", second)
        self.assertTrue(self._ids_in(second))
        self.assertEqual(set(self._ids_in(first)) & set(self._ids_in(second)), set())

    def test_the_pager_keeps_the_filter_it_was_paging(self) -> None:
        """A filtered page two has to stay filtered, or the pager quietly changes the question.

        It is the sort of thing nobody notices: the table redraws, the rows are plausible, and the
        filter select still says "Settled" while the rows underneath are everything.
        """
        html = self._html("/billing/list/?paid=paid")

        self.assertIn("&amp;paid=paid", html)

    # --- detail -----------------------------------------------------------------------------------

    def test_the_detail_renders_the_invoice_with_its_chain_and_its_payments(
        self,
    ) -> None:
        """A real invoice paints the three to-one hops flattened and the to-many under them."""
        invoice_id = self._an_invoice_with_payments()

        html = self._html(f"/billing/detail/{invoice_id}/")

        self.assertIn("Invoice #", html)
        self.assertIn('aria-label="Payments against this invoice"', html)
        self.assertIn("<dt>Outstanding</dt>", html)
        self.assertIn("<dt>Paid so far</dt>", html)

    def test_an_invoice_that_is_not_there_answers_404(self) -> None:
        """`not_found` from the view model becomes a 404 with the error page, not an empty detail."""
        response = self.client.get("/billing/detail/999999/")

        self.assertEqual(response.status_code, 404)
        self.assertIn("That invoice does not exist", response.content.decode())

    def test_an_unpaid_invoice_still_has_a_detail_page(self) -> None:
        """The outstanding half of the fork opens too, and it is the one the report counts."""
        invoice_id = self._an_invoice(paid=False)

        html = self._html(f"/billing/detail/{invoice_id}/")

        self.assertIn("Invoice #", html)
        self.assertIn("Outstanding", html)

    # --- report -----------------------------------------------------------------------------------

    def test_the_report_renders_its_three_answers_with_real_figures(self) -> None:
        """Every section is on the page, and the two tables did not fall back to their empty rows."""
        html = self._html("/billing/report/")

        self.assertIn('aria-label="Plans and subscribers"', html)
        self.assertIn('aria-label="Revenue by plan"', html)
        self.assertIn("<dt>Outstanding invoices</dt>", html)
        self.assertNotIn("&mdash; no plans &mdash;", html)
        self.assertNotIn("&mdash; nothing has been invoiced &mdash;", html)

    def test_the_report_says_which_threshold_the_having_applied(self) -> None:
        """A filtered list whose filter is not named is a list nobody can reproduce.

        The threshold comes back on the context as formatted money precisely so the page can say it,
        which is the difference between a figure a reader can check and one they have to trust.
        """
        html = self._html("/billing/report/")

        self.assertIn("having(sum(...) &gt;= 0.01)", html)

    def test_the_report_says_something_about_the_silent_plans_either_way(self) -> None:
        """The gap between the two tables is NAMED, whether there is one or not.

        A section that renders nothing when the answer is "none" leaves a reader unable to tell an
        empty answer from a broken query, and this figure is the one the page exists for: a plan with
        subscribers and no revenue is either a tariff nobody is being billed for or a billing job
        that stopped running.
        """
        html = self._html("/billing/report/")

        found = "with subscribers and no" in html
        clean = "Every plan with a subscriber has invoiced something" in html
        self.assertNotEqual(
            found, clean, "the silent-plans section said both or neither"
        )

    # --- the three pages that do not exist --------------------------------------------------------

    def test_the_domain_offers_no_way_to_write_an_invoice(self) -> None:
        """THE ABSENCE, asserted in the router rather than only in the catalogue.

        `shared/tests/test_nav.py` already says the catalogue offers billing three pages. This says
        the DEMO offers three, which is a different claim: a route can exist without a sidebar link,
        and the one thing this domain must never grow is a form over an amount.
        """
        for name in ("billing_create", "billing_update", "billing_delete"):
            with self.assertRaises(NoReverseMatch, msg=name):
                reverse(name)

        for url in ("/billing/create/", "/billing/update/1/", "/billing/delete/1/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_no_page_of_this_domain_offers_a_button_that_writes(self) -> None:
        """The router is one half; a form posting somewhere else would be the other.

        Billing renders no `<form method="post">` at all — the only form on any of these pages is the
        filter, which is a GET. A POST form here would mean the read-only domain grew a write, and it
        would be doing it through somebody else's route.
        """
        invoice_id = self._an_invoice(paid=False)
        pages = (
            "/billing/list/",
            f"/billing/detail/{invoice_id}/",
            "/billing/report/",
        )

        for url in pages:
            html = self._html(url)
            self.assertNotIn('method="post"', html.lower(), url)

    # --- the shell --------------------------------------------------------------------------------

    def test_every_page_carries_the_sidebar_and_it_shows_billing(self) -> None:
        """The context processor is what makes this true of pages no view of ours remembered."""
        invoice_id = self._an_invoice(paid=True)
        pages = (
            "/billing/list/",
            f"/billing/detail/{invoice_id}/",
            "/billing/report/",
        )

        for url in pages:
            html = self._html(url)
            self.assertIn('<nav class="sidebar" aria-label="Domains">', html)
            self.assertIn('href="/billing/list/"', html)
            self.assertIn('href="/billing/report/"', html)
            self.assertIn("Invoices", html)

    def test_the_sidebar_marks_the_billing_page_you_are_on(self) -> None:
        """`aria-current` rides on the link of the route being served, and on no other."""
        listing = self._html("/billing/list/")
        self.assertIn('href="/billing/list/" aria-current="page"', listing)
        self.assertNotIn('href="/billing/report/" aria-current="page"', listing)

        report = self._html("/billing/report/")
        self.assertIn('href="/billing/report/" aria-current="page"', report)
        self.assertNotIn('href="/billing/list/" aria-current="page"', report)
