"""The React demo's sidebar says the SAME thing as the shared catalogue, section by section.

`shared/web/nav.py` is the catalogue: WHICH sections the demos have and WHICH pages hang off each
one, said without a single URL, because Django reverses a route by name and Flask by endpoint. The
React demo needs the same list and cannot import it — it runs in a browser — so it restates it, and
adds the one thing the Python catalogue deliberately refuses to hold: a client-side path, since
React Router locates a page by path and by nothing else.

THAT IS A FOURTH COPY OF A LIST THIS REPOSITORY ALREADY KNOWS DRIFTS. The catalogue exists because
two SSR demos had started disagreeing about what pages existed; a third language holding the same
list by hand is the same failure with a compiler that cannot see it. So this walks both and fails
naming the section that moved.

IT READS THE ROUTES THEMSELVES, which is what changed when the React demo went domain-first. There
used to be a `config/nav.ts` — a second list, beside the router, repeating every path and label — and
this test read that. Now each domain declares its routes once in `domains/<name>/routes.tsx`, the
sidebar is walked from those declarations, and a page appears in it when its route carries a `nav`.
So this reads the same declaration the app does: there is no separate catalogue left to check
against, which is the point of the refactor and makes this net stronger rather than weaker.

WHAT IT COMPARES. The sections, their ORDER, which pages each one puts in the sidebar with which
label, and — since the gap below — EVERY page the catalogue names, sidebar or not.

That last one is the important half and it was missing. The sidebar holds `list`, `create` and the
reports; what it cannot hold is anything that needs a key, because a sidebar link has nowhere to get
one. So `detail`, `update` and `delete` were checked by nothing at all — and that is exactly where
the React demo turned out to be short a page: `orders.delete` existed in Django and in Flask and not
here, and no net said so. It was found by comparing the two by hand.

The two catalogues name the pages IDENTICALLY, and that is a decision rather than a coincidence. The
alternative was a translation table in this file — "when Python says `delete`, look for `remove`" —
and a translation table is a place where a missing page can be made to disappear with one line. The
names were changed on the TypeScript side instead, so there is nowhere to hide a difference.

It does NOT compare the blurbs: prose, and a test demanding two paragraphs match character for
character fails on a typo fix.

It reads the TypeScript with a regex rather than a parser, and that is bounded rather than lazy:
what it needs is one field out of an object literal that this test is itself the reason to keep flat.
A parser would be a dependency in a demo that boots with `uv` alone, and the failure mode is loud —
a file it cannot read is a section it reports as EMPTY, never one it skips.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from shared.web.nav import SECTIONS, NavSection

_REACT = pathlib.Path(__file__).resolve().parents[2] / "react_front" / "src"
_DOMAINS = _REACT / "domains"
_REGISTRY = _REACT / "config" / "routes.ts"

# `{ domain: "blog", label: "Blog" },` in the SIDEBAR array — the sections and their order.
_SIDEBAR_ENTRY = re.compile(
    r'\{\s*domain:\s*"(?P<domain>[^"]+)",\s*label:\s*"(?P<label>[^"]+)"\s*\}'
)

# A route entry that carries a `nav`, which is what puts it in the sidebar. The key is the action.
_NAV_ROUTE = re.compile(
    r'^\s*(?P<action>\w+):\s*\{[^}\n]*?nav:\s*"(?P<label>[^"]+)"',
    re.MULTILINE,
)

# ANY route entry, sidebar or not. The key is the action the catalogue names it by.
_ANY_ROUTE = re.compile(r"^\s*(\w+):\s*\{ segment:", re.MULTILINE)

# `export` is the one catalogue action with no route on this side, and the absence is structural: what
# it reaches is a STREAMED CSV, so the sidebar links straight at the API. A page that rendered a file
# would be a page about nothing. Django gives it a `_URL_NAMES` entry for the same reason and with the
# same argument — "the sidebar's job is to reach the route, and what the route hands back is the
# route's business".
_NOT_A_PAGE = {"export"}


def _sidebar_sections() -> list[tuple[str, str]]:
    """`(domain, label)` for each section, in the order the registry declares them."""
    source = _REGISTRY.read_text(encoding="utf-8")
    start = source.index("export const SIDEBAR")
    return [(m["domain"], m["label"]) for m in _SIDEBAR_ENTRY.finditer(source[start:])]


def _react_sidebar_pages(domain: str) -> list[tuple[str, str]]:
    """`(action, label)` for the pages a domain puts in the sidebar, in declaration order."""
    routes = _DOMAINS / domain / "routes.tsx"
    if not routes.exists():
        return []
    return [
        (m["action"], m["label"])
        for m in _NAV_ROUTE.finditer(routes.read_text(encoding="utf-8"))
    ]


def _react_actions(domain: str) -> set[str]:
    """EVERY route a domain declares, by its key. The sidebar ones and the ones that need a key."""
    routes = _DOMAINS / domain / "routes.tsx"
    if not routes.exists():
        return set()
    return set(_ANY_ROUTE.findall(routes.read_text(encoding="utf-8")))


def _python_sidebar_pages(section: NavSection) -> list[tuple[str, str]]:
    """The same, out of the catalogue that is the source of truth.

    The `export` pages are dropped: what they reach is a streamed CSV and not a page, so the React
    demo has no route for one — the sidebar links straight at the API, which is the same entry
    Django's `_URL_NAMES` gives them and for the same stated reason.
    """
    return [
        (page.action, page.label)
        for page in section.pages
        if page.in_sidebar and page.action != "export"
    ]


def test_the_react_registry_is_readable() -> None:
    """The registry parses into sections at all. Without this every comparison passes vacuously."""
    assert _REGISTRY.exists(), f"{_REGISTRY} is missing"
    assert _sidebar_sections(), f"no sections could be read out of {_REGISTRY.name}"


def test_both_catalogues_list_the_same_domains_in_the_same_order() -> None:
    """Same sections, same order — because the order IS the sidebar's order."""
    assert [domain for domain, _ in _sidebar_sections()] == [
        section.domain for section in SECTIONS
    ]


def test_the_section_labels_agree() -> None:
    """What each section is CALLED. `taxonomy` is labelled `Tags`, which is the kind of thing that drifts."""
    assert _sidebar_sections() == [
        (section.domain, section.label) for section in SECTIONS
    ]


@pytest.mark.parametrize("section", SECTIONS, ids=lambda section: section.domain)
def test_a_section_offers_the_same_sidebar_pages(section: NavSection) -> None:
    """One case per domain, so a failure NAMES the section that drifted instead of dumping a list."""
    assert _react_sidebar_pages(section.domain) == _python_sidebar_pages(section)


@pytest.mark.parametrize("section", SECTIONS, ids=lambda section: section.domain)
def test_a_section_serves_every_page_the_catalogue_names(section: NavSection) -> None:
    """EVERY page, and not only the ones the sidebar can reach. This is the half that was missing.

    A page that needs a key — `detail`, `update`, `delete` — cannot be in the sidebar, so until this
    existed nothing compared them at all. `orders.delete` was absent from the React demo for exactly
    that reason: Django served it, Flask served it, and no net could see that the fourth did not.

    A framework is free to register MORE routes than the catalogue names, which is why this is a
    subset check and not an equality: Django does it too — `orders_operate_index` and
    `orders_operate` are two of its routes for the catalogue's single `operate`, because a chooser
    with no key and an operation with one cannot be the same URL.
    """
    wanted = {page.action for page in section.pages} - _NOT_A_PAGE
    missing = sorted(wanted - _react_actions(section.domain))

    assert missing == [], (
        f"the React demo has no page for these `{section.domain}` actions: {missing}. Django and "
        f"Flask serve them, so the fourth demo is short a page — or the route key does not match "
        f"the catalogue's name, which is the same failure wearing a different hat."
    )
