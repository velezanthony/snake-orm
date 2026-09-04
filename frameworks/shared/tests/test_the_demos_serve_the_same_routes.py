"""The three demos are MIRRORS, and this is what turns that claim into a fact.

The premise of `frameworks/` is that one domain layer serves three frameworks: the same operations,
the same answers, only the plumbing changes. Two nets already hold the layer itself together —
`test_async_mirror.py` (same names, same parameters) and `test_sync_async_parity.py` (same answer,
same SQL, same message). What NOTHING was watching is the surface: which pages and which endpoints
each demo actually exposes.

That gap is not theoretical. A domain gains a router in one demo and not in the other two, every
suite stays green, and the demos quietly stop being comparable — which is the whole reason somebody
reads three of them side by side. The reader who wants to know "how do I do this in Flask" finds a
page in the Django demo and nothing here, and concludes the ORM cannot.

TWO SURFACES, TWO TESTS, because they are two different promises:

- **SSR** is Django against Flask. FastAPI has no HTML on purpose — it is the JSON demo — so a third
  column there would be a column of blanks.
- **The API** is all three, and it is the one that has to be identical: a BFF mirror where `/api/X`
  answers the same question the SSR page asks.

The routes are read with `ast` and never by booting the apps; `routes.py` beside this file explains
why, and it is the same reason `test_nav_is_wired_in_both_demos.py` gives.
"""

from __future__ import annotations

import pytest

from shared.tests.routes import django_routes, fastapi_routes, flask_routes

# What the SSR demos are ALLOWED to spell differently, each with the reason it is not drift. A
# mapping and not a set, for the same purpose the `Cap` catalogue is one: the next person has to be
# able to tell a decision from an oversight, and a bare path in a list explains neither.
_SSR_SPELLINGS: dict[str, str] = {
    "/lab": (
        "Django mounts the lab's index at the empty path of its own include, so the listing IS "
        "`/lab`; Flask names it `/lab/list`. Same page, and each spelling is the idiomatic one for "
        "its router — Django reverses `lab:list`, Flask `url_for('lab.list')`"
    ),
    "/lab/list": "the Flask half of the pair above",
    "/posts": (
        "Flask serves the blog listing at `/` AND at `/posts`; Django serves it only at `/`. The "
        "alias is Flask's, it answers the same view, and dropping it would change a demo's URLs to "
        "satisfy a test rather than a reader"
    ),
}

# The endpoints that are the FRAMEWORK's own plumbing and not a domain's answer: the OpenAPI
# document and the browser that renders it. Each framework puts them somewhere different by
# convention —`/api/schema` on drf-spectacular, `/api/openapi.json` on flask-smorest, `/openapi.json`
# on FastAPI— and demanding one spelling would mean fighting three conventions to compare something
# that is not the demo's API at all.
_NOT_A_DOMAIN_ENDPOINT: dict[str, str] = {
    "/api/docs": "the Swagger UI, mounted by the framework's own extension",
    "/api/schema": "drf-spectacular's OpenAPI document",
    "/api/openapi.json": "flask-smorest's OpenAPI document",
}

# The API surface a demo is knowingly missing, with what it owes. THIS IS A DEBT AND IT IS WRITTEN
# DOWN, which is the only honest way to keep a suite green over a known hole: `test_no_exemption_
# outlives_its_reason` below deletes the excuse the day the routes appear, so the entry cannot rot
# into a decision nobody remembers making.
_OWED: dict[str, str] = {
    # Empty, and that is the point of keeping it: `orders` lived here while its JSON surface existed
    # only on FastAPI, and the entry came off the day Django and Flask grew theirs — which is what
    # `test_no_exemption_outlives_its_reason` forces. A debt catalogue that never empties is a
    # catalogue nobody believes.
}


def _api(routes: set[str]) -> set[str]:
    """A demo's API surface: what hangs off `/api/` and answers for a DOMAIN.

    The framework's own document and its browser are dropped by name because they are the one thing
    under `/api/` that no domain owns; everything else is compared exactly.
    """
    return {
        route
        for route in routes
        if route.startswith("/api/") and route not in _NOT_A_DOMAIN_ENDPOINT
    }


def _ssr(routes: set[str]) -> set[str]:
    """A demo's HTML surface: everything that is not the API."""
    return {route for route in routes if not route.startswith("/api")}


_SURFACES = {
    "django": django_routes(),
    "flask": flask_routes(),
    "fastapi": fastapi_routes(),
}


def test_the_reader_found_routes_in_all_three_demos() -> None:
    """That the source scan found anything at all, which is the trap of every self-discovering check.

    A parser that stops matching —a decorator renamed, a mount written another way— returns an empty
    set, every comparison below succeeds over nothing, and the suite reports that three demos agree
    when it has not looked at one. It is the same vacuous-run guard `test_async_mirror.py` opens with
    and for the same reason: this file's failure mode is silence, not noise.
    """
    empty = sorted(demo for demo, routes in _SURFACES.items() if not routes)

    assert empty == [], (
        f"no routes read out of {empty}: the demo stopped declaring them the way `routes.py` reads, "
        f"and every comparison in this file would now pass over an empty set."
    )
    assert _api(_SURFACES["fastapi"]), (
        "the FastAPI demo is the API one and read as having none"
    )
    assert _ssr(_SURFACES["django"]), (
        "the Django demo is an SSR one and read as having no pages"
    )


def test_the_two_ssr_demos_serve_the_same_pages() -> None:
    """Django and Flask show the SAME pages, and the exceptions are spellings with a reason.

    This is the comparison a reader makes without being asked: the two SSR demos exist so that "how
    does this look in my framework" has an answer, and a page present in one and missing in the
    other turns that into "it cannot be done here" — which is false, and which nothing was checking.

    FastAPI is not in this test on purpose. It serves no HTML, and its absence is a decision the
    repository makes out loud rather than a gap: the JSON demo is where the asynchronous session
    lives, and giving it templates would make it a second Flask.
    """
    django = _ssr(_SURFACES["django"]) - set(_SSR_SPELLINGS)
    flask = _ssr(_SURFACES["flask"]) - set(_SSR_SPELLINGS)

    assert django == flask, (
        f"the two SSR demos do not show the same pages.\n"
        f"  only Django: {sorted(django - flask)}\n"
        f"  only Flask : {sorted(flask - django)}\n"
        f"Either serve the missing page, or add its path to `_SSR_SPELLINGS` above WITH the reason "
        f"the two demos are entitled to spell it differently."
    )


@pytest.mark.parametrize("demo", sorted(_SURFACES))
def test_the_three_demos_expose_the_same_api(demo: str) -> None:
    """Every demo answers the SAME `/api/` endpoints, or owes them in writing.

    The API is the half where identical is the point rather than a nicety. These three are a BFF
    mirror: `/api/X` answers in JSON the question the `/X` page asks in HTML, and the reason all
    three exist is that somebody can hold them side by side and see one domain layer wearing three
    frameworks. An endpoint in one and not the others breaks exactly that.

    The comparison is against the UNION of the three rather than pairwise, so a domain added to one
    demo names the two that now owe it instead of producing three failures that each blame the wrong
    file.
    """
    everywhere = set().union(*(_api(routes) for routes in _SURFACES.values()))
    missing = sorted(everywhere - _api(_SURFACES[demo]))

    assert missing == [] or demo in _OWED, (
        f"`{demo}` does not answer these and no debt is written for it: {missing}. Either add the "
        f"routes or record what it owes in `_OWED` above, with the reason."
    )


def test_no_exemption_outlives_its_reason() -> None:
    """A debt disappears when it is paid, and a spelling when the two demos agree on one.

    This is the half that keeps the two catalogues above from rotting. An exemption nobody removes
    reads, a year later, as a decision that was made — and it is really a note about a route somebody
    added while nobody was looking. The same bargain the skip catalogues in `conftest.py` strike:
    a written reason has to expire when it is spent.
    """
    everywhere = set().union(*(_api(routes) for routes in _SURFACES.values()))
    paid = sorted(demo for demo in _OWED if not everywhere - _api(_SURFACES[demo]))

    stale_spellings = sorted(
        path
        for path in _SSR_SPELLINGS
        if path not in _ssr(_SURFACES["django"]) | _ssr(_SURFACES["flask"])
    )

    assert paid == [], (
        f"these have paid what `_OWED` says they owe: {paid}. Strike them off — the entry beside "
        f"them is now fiction, and fiction in a debt catalogue is how the next hole gets excused."
    )
    assert stale_spellings == [], (
        f"these paths are in `_SSR_SPELLINGS` and neither demo serves them any more: "
        f"{stale_spellings}. The exemption is describing a route that no longer exists."
    )
