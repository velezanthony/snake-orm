"""Every section the catalogue offers is one both demos can actually reverse into a link.

`shared/web/nav.py` names the sections; each demo maps `(domain, action)` to its own route. That
split is deliberate and it is the right one — two routers already answer "where is this", and a path
written into the catalogue would be a third answer that nothing executes. But a split invents a
JOINT, and nothing was watching this one.

It broke the first time it was tested. The `orders` section went into the catalogue one step before
either demo learned to reverse it, and both sidebars are rendered by a context processor that runs on
EVERY page: `ENDPOINTS[domain, action]` raised `KeyError: ('orders', 'list')` on the blog, on the lab,
on the login form. Sixteen of Django's twenty-six tests errored and twelve of Flask's sixteen. The
`KeyError` is deliberate —a template asking for a domain that does not exist has a typo in it, and
the useful outcome is a loud one— and it worked exactly as designed. Nobody was listening, because
the run that had just gone green was the SHARED suite, and the shared suite does not render a page.

So this is the cheap listener. It reads the two maps out of the demos' source with `ast` instead of
importing them: importing means booting Django's settings and Flask's app from inside a suite whose
whole premise is an in-memory SQLite and no server, and a check that needs a framework to run is a
check that gets skipped on the day it matters.

It guards BOTH directions, and the second one is not decoration: an entry left behind after a section
is renamed still reverses, still paints a link, and points at a page that no longer exists.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from shared.web.nav import sidebar_sections

_ROOT = pathlib.Path(__file__).resolve().parents[2]

# The two demos with templates, and the name each gives the map. They differ —Flask's is public
# because its context processor lives in another module, Django's is private to the processor beside
# it— and that is a fact about the two demos rather than drift: the RULE is that a map exists and
# says the same thing, not that it wears the same name.
_MAPS = {
    "flask": ("flask/apps/nav.py", "ENDPOINTS"),
    "django": ("django/apps/nav.py", "_URL_NAMES"),
}


def _mapped_pairs(demo: str) -> set[tuple[str, str]]:
    """The `(domain, action)` keys a demo can reverse, read from its source without importing it."""
    relative, name = _MAPS[demo]
    tree = ast.parse((_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        if not isinstance(target, ast.Name) or target.id != name:
            continue
        if not isinstance(value, ast.Dict):
            continue
        pairs = (_string_pair(key) for key in value.keys)
        return {pair for pair in pairs if pair is not None}
    raise AssertionError(f"{relative} no longer declares a dict called {name}")


def _string_pair(key: ast.expr | None) -> tuple[str, str] | None:
    """A `("domain", "action")` literal read out of the AST, or `None` if it is anything else.

    A function and not a condition inside the comprehension, and for a reason worth the line:
    `all(isinstance(element, ast.Constant) for element in key.elts)` reads correctly to a human and
    narrows NOTHING for the type checker, so `key.elts[0].value` was an attribute on `ast.expr`
    that may not have one. Two named checks narrow; a generator expression over them does not.
    """
    if not isinstance(key, ast.Tuple) or len(key.elts) != 2:
        return None
    first, second = key.elts
    if not isinstance(first, ast.Constant) or not isinstance(second, ast.Constant):
        return None
    if not isinstance(first.value, str) or not isinstance(second.value, str):
        return None
    return first.value, second.value


def _linkable_pairs() -> set[tuple[str, str]]:
    """What the catalogue asks a sidebar to link: the pages marked `in_sidebar`, and only those.

    The other three —`detail`, `update`, `delete`— need a key, and a sidebar link has nowhere to get
    one. Demanding an entry for them would be demanding a route that can only 404.
    """
    return {
        (section.domain, page.action)
        for section in sidebar_sections()
        for page in section.pages
        if page.in_sidebar
    }


def test_the_catalogue_and_both_maps_are_not_empty() -> None:
    """All three sides have entries, so a passing run below means something.

    It is the trap of any check that reads its own input: if the parse stops matching, "nothing is
    missing" holds over an empty set and the guard becomes decoration.
    """
    assert len(_linkable_pairs()) >= 6
    for demo in _MAPS:
        assert len(_mapped_pairs(demo)) >= 6, demo


@pytest.mark.parametrize("demo", sorted(_MAPS), ids=str)
def test_every_sidebar_page_is_one_this_demo_can_reverse(demo: str) -> None:
    """A section in the catalogue with no route in a demo is a `KeyError` on EVERY page of it.

    Not on the page it belongs to — on every page, because the sidebar is rendered by a context
    processor. The whole demo goes down over one missing line, which is how a green shared suite
    once sat next to two demos that answered 500 to everything.
    """
    missing = sorted(_linkable_pairs() - _mapped_pairs(demo))

    assert missing == [], (
        f"{demo} cannot reverse these, and its sidebar raises on every page it renders: {missing}. "
        f"Add them to the map in {_MAPS[demo][0]} — the catalogue names the page, the demo locates it."
    )


@pytest.mark.parametrize("demo", sorted(_MAPS), ids=str)
def test_no_demo_maps_a_page_the_catalogue_no_longer_offers(demo: str) -> None:
    """A leftover entry is worse than a missing one: it reverses, paints a link, and 404s.

    A missing entry is loud on the first page load. A stale one is silent until somebody clicks it,
    which is exactly the sort of rot a renamed section leaves behind.
    """
    stale = sorted(_mapped_pairs(demo) - _linkable_pairs())

    assert stale == [], (
        f"{demo} maps these and the catalogue does not offer them any more: {stale}. Either the "
        f"section was renamed and this entry was left behind, or the page stopped being "
        f"`in_sidebar` and its link now points at nothing."
    )
