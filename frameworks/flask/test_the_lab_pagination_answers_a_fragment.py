"""The lab's pager answers a FRAGMENT to HTMX and the whole page to a browser, off ONE url.

WHY ONE URL AND NOT TWO. A sibling route serving the fragment would mean every pager link carries two
addresses — an `href` for the browser and an `hx-get` for HTMX — and two addresses for one answer is
how the fragment and the page end up showing different rows. `apps/lab/urls.py` opens by saying it is
a correction of exactly that shape: two copies of one page's meaning, already drifted. So the page
negotiates instead: HTMX sends `HX-Request`, the view picks the partial, and the `href` and the
`hx-get` are the same string.

WHY IT STILL WORKS WITH JAVASCRIPT OFF, which is the property this replaces a working page with a
library for. The links stay real `<a href>`: with no HTMX loaded, the browser follows them and gets
the full page, because nothing sent the header. That is not a nicety here — it is the difference
between an enhancement and a rewrite.

`Vary: HX-Request` is asserted for the same reason it is set. The two answers share a url, so a cache
that keeps the first one keys on the header or serves a bare fragment to a full navigation — the back
button being the everyday way to see it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import django_htmx
import pytest
from flask.testing import FlaskClient

from app import create_app

app = create_app()

_PAGE = "/lab/pagination"
_HTMX = {"HX-Request": "true"}


@pytest.fixture(scope="module")
def client() -> Iterator[FlaskClient]:
    """One client for the whole file: nothing here writes, so nothing needs a fresh database."""
    with app.test_client() as test_client:
        yield test_client


def test_a_browser_gets_the_whole_page(client: FlaskClient) -> None:
    """No `HX-Request` header, no negotiation: the shell, the sidebar and the pager."""
    body = client.get(_PAGE).get_data(as_text=True)

    assert "<html" in body
    assert 'id="lab-pagination"' in body


def test_htmx_gets_only_the_pager(client: FlaskClient) -> None:
    """With the header, the answer is the panel alone — no shell, no sidebar, no `<html>`."""
    response = client.get(f"{_PAGE}?page=1", headers=_HTMX)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<html" not in body
    assert "<nav" in body and 'id="lab-pagination"' in body
    assert "topbar" not in body, "the shell came along: the view rendered the full page"


def test_the_fragment_swaps_itself_whole(client: FlaskClient) -> None:
    """The panel carries its own id and swaps `outerHTML`, so a swap can be followed by another.

    A fragment that arrives without the element HTMX aimed at replaces it with something that has no
    target in it, and the SECOND page turn silently does nothing. It is the one failure of this
    pattern that a first click never shows.
    """
    body = client.get(f"{_PAGE}?page=1", headers=_HTMX).get_data(as_text=True)

    assert 'hx-target="#lab-pagination"' in body
    assert 'hx-swap="outerHTML"' in body


def test_going_back_gets_the_whole_page_again(client: FlaskClient) -> None:
    """A history restore is an HTMX request that wants the PAGE, and it says so in a header.

    htmx re-requests a page whose snapshot has rolled out of its cache with `HX-Request: true` AND
    `HX-History-Restore-Request: true`, then swaps what comes back into the whole `<body>`. Answer
    that with the fragment and pressing Back leaves a bare table where the demo was.
    """
    headers = {**_HTMX, "HX-History-Restore-Request": "true"}

    assert "<html" in client.get(_PAGE, headers=headers).get_data(as_text=True)


def test_the_page_really_moved(client: FlaskClient) -> None:
    """Page 1 is not page 0. Without this, the two assertions above hold over an empty pager."""
    first = client.get(f"{_PAGE}?page=0", headers=_HTMX).get_data(as_text=True)
    second = client.get(f"{_PAGE}?page=1", headers=_HTMX).get_data(as_text=True)

    assert "OFFSET 0" in first
    assert "OFFSET 20" in second


def test_every_pager_link_is_a_real_link(client: FlaskClient) -> None:
    """`href` and `hx-get` are the same address, so the page pages with JavaScript switched off."""
    body = client.get(f"{_PAGE}?page=1").get_data(as_text=True)

    assert f'href="{_PAGE}?page=0" hx-get="{_PAGE}?page=0"' in body
    assert f'href="{_PAGE}?page=2" hx-get="{_PAGE}?page=2"' in body


def test_the_two_answers_are_told_apart_by_caches(client: FlaskClient) -> None:
    """`Vary: HX-Request`, because one url answers two ways."""
    response = client.get(_PAGE, headers=_HTMX)

    assert "HX-Request" in response.headers.get("Vary", "")


def test_the_htmx_this_demo_serves_is_the_one_django_serves(
    client: FlaskClient,
) -> None:
    """Byte for byte the file `{% htmx_script %}` hands the Django demo. Not a copy of it — it.

    This is the whole reason a Flask app imports a Django package. Two committed copies would need
    somebody to remember to move them together, and they would go on working while they drifted;
    here there is one file and nothing to keep in step. The assertion is bytes rather than a version
    string because a version string is what a stale copy also has.
    """
    served = client.get("/vendor/htmx-2.min.js")
    package_file = (
        Path(django_htmx.__file__).parent / "static" / "django_htmx" / "htmx-2.min.js"
    )

    assert served.status_code == 200
    assert served.get_data() == package_file.read_bytes()
