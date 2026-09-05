"""The lab's pager answers a FRAGMENT to HTMX and the whole page to a browser, off ONE url.

The twin of `flask/test_the_lab_pagination_answers_a_fragment.py`, and the reasoning is the same one
`shared/web/lab_pages.py` sets out at length: one url, negotiated, because a sibling route for the
fragment puts two addresses on every pager link and two addresses for one answer is how a fragment
ends up showing different rows from the page it replaces.

WHAT IS ASSERTED HERE AND NOT THERE: which htmx this demo loads. `{% htmx_script %}` takes a version
and defaults to 2, and the Flask demo serves `htmx-2.min.js` out of this very package. If somebody
passes `version=4` here, the two demos are running different libraries off the same install and
nothing else in the suite would notice — while every behavioural difference between the demos starts
having to ask "is it the framework, or is it htmx?" first.

`SimpleTestCase`: the rows are SnakeORM's, and Django's ORM holds none of this.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from django.test import Client, SimpleTestCase, override_settings

from apps.blog import seed

_PAGE = "/lab/pagination"
_HTMX = {"HX-Request": "true"}


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"])
class LabPaginationFragmentTests(SimpleTestCase):
    """The two answers of one url, and the library the page loads to ask for the second."""

    databases: set[str] | Literal["__all__"] = set()

    @classmethod
    def setUpClass(cls) -> None:
        """Seeds once: nothing in this file writes, so one seeded database serves every test."""
        super().setUpClass()
        seed.reset_and_seed()

    def setUp(self) -> None:
        """A client per test."""
        self.client = Client()

    def _body(self, url: str, *, headers: Mapping[str, str] | None = None) -> str:
        """The response body as text.

        `headers` is spelled out rather than swallowed by a `**kwargs: object`: splatting `object`
        into `Client.get` hands `object` to every one of its typed parameters at once, which is
        five pyright errors from one line and none of them about anything real. The seven callers
        here pass this and nothing else.
        """
        return self.client.get(url, headers=headers).content.decode()

    def test_a_browser_gets_the_whole_page(self) -> None:
        """No `HX-Request` header, no negotiation: the shell, the sidebar and the pager."""
        body = self._body(_PAGE)

        self.assertIn("<html", body)
        self.assertIn('id="lab-pagination"', body)

    def test_htmx_gets_only_the_pager(self) -> None:
        """With the header, the answer is the panel alone — no shell, no sidebar, no `<html>`."""
        response = self.client.get(f"{_PAGE}?page=1", headers=_HTMX)
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<html", body)
        self.assertIn('id="lab-pagination"', body)
        self.assertNotIn(
            "topbar", body, "the shell came along: the view rendered the full page"
        )

    def test_the_fragment_swaps_itself_whole(self) -> None:
        """The panel carries its own id and swaps `outerHTML`, so a swap can be followed by another.

        A fragment that arrives without the element HTMX aimed at replaces it with something that has
        no target in it, and the SECOND page turn silently does nothing. It is the one failure of
        this pattern that a first click never shows.
        """
        body = self._body(f"{_PAGE}?page=1", headers=_HTMX)

        self.assertIn('hx-target="#lab-pagination"', body)
        self.assertIn('hx-swap="outerHTML"', body)

    def test_going_back_gets_the_whole_page_again(self) -> None:
        """A history restore is an HTMX request that wants the PAGE, and it says so in a header.

        htmx re-requests a page whose snapshot has rolled out of its cache with `HX-Request: true`
        AND `HX-History-Restore-Request: true`, then swaps what comes back into the whole `<body>`.
        Answer that with the fragment and pressing Back leaves a bare table where the demo was.
        """
        body = self._body(
            _PAGE, headers={**_HTMX, "HX-History-Restore-Request": "true"}
        )

        self.assertIn("<html", body)

    def test_the_page_really_moved(self) -> None:
        """Page 1 is not page 0. Without this, the assertions above hold over an empty pager."""
        self.assertIn("OFFSET 0", self._body(f"{_PAGE}?page=0", headers=_HTMX))
        self.assertIn("OFFSET 20", self._body(f"{_PAGE}?page=1", headers=_HTMX))

    def test_every_pager_link_is_a_real_link(self) -> None:
        """`href` and `hx-get` are the same address, so the page pages with JavaScript switched off."""
        body = self._body(f"{_PAGE}?page=1")

        self.assertIn(f'href="{_PAGE}?page=0" hx-get="{_PAGE}?page=0"', body)
        self.assertIn(f'href="{_PAGE}?page=2" hx-get="{_PAGE}?page=2"', body)

    def test_the_two_answers_are_told_apart_by_caches(self) -> None:
        """`Vary: HX-Request`, because one url answers two ways."""
        response = self.client.get(_PAGE, headers=_HTMX)

        self.assertIn("HX-Request", response.headers.get("Vary", ""))

    def test_the_page_loads_the_htmx_the_flask_demo_serves(self) -> None:
        """htmx 2, out of `django-htmx`. The Flask demo serves that same file from that same path."""
        body = self._body(_PAGE)

        self.assertIn("django_htmx/htmx-2.min.js", body)
