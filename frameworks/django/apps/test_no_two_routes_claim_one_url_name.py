"""No two routes of this demo claim the same url NAME, because the second one wins in silence.

WHAT THIS COSTS WHEN NOBODY IS WATCHING, measured on this demo rather than imagined. `web_urls.py`
names the receive and ship PAGES `inventory_receive` and `inventory_ship`; `urls.py` named the two
JSON endpoints the same, and `urls.py` is included second, so `reverse("inventory_receive", [1, 2])`
answered `/api/inventory/warehouses/1/stock/2/receive`. That expression is what
`templates/inventory/detail/inventory_detail.html` puts in the `action` of both of its forms. A
reader pressing "Receive" on the stock sheet was posting the form at DRF and getting a JSON document
back instead of the page they were standing on — and the same collision, freshly made on `report`
and `export`, put the Inventory sidebar's "Report" and "Export CSV" links on `/api/inventory/report`
and `/api/inventory/export`.

WHY EVERY OTHER NET LOOKED STRAIGHT THROUGH IT, which is the whole reason this file exists.
`test_every_route_answers.py` walks the URLconf and calls each route: both of a colliding pair are
declared, both answer, and neither raises. `shared/tests/test_the_demos_serve_the_same_routes.py`
compares the PATHS the three demos serve, and the paths were right — the collision is not in a path.
`shared/tests/test_the_page_and_the_api_reach_one_usecase.py` joins routes to use cases and both
routes reach theirs. `test_demo_templates_match.py` compares template names, and the damage is
inside one attribute of one tag. Django itself says nothing: two `path()` calls may share a name,
and `reverse()` simply picks the last one registered.

So a url name is the one thing in this demo that two files can claim with nothing at all being said,
and the only way to find out is to ask the resolver — which is what this does, over the real
URLconf rather than over a list, so a route added tomorrow is covered without anybody remembering.

THE RULE THAT COMES OUT OF IT, and it is written where it is enforced: in a domain that serves BOTH
surfaces, the pages keep the bare name and the endpoint takes `_api`. The pages had the name first
and the templates are what reverse it; an endpoint is reached by a client that types the URL.
`apps/billing/urls.py` already spelt its report `billing_report_api` for exactly this reason, and
`apps/inventory/urls.py` now spells four of its own the same way.

`SimpleTestCase`: this reads the URLconf and touches no row.
"""

from __future__ import annotations

import collections

from django.test import SimpleTestCase
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver


def _names() -> dict[tuple[str, str], list[str]]:
    """Every `(namespace, name)` this demo registers, mapped to the routes that claim it.

    The namespace travels with the name because it is half of the key `reverse()` resolves on: the
    lab is included under one and everything else is not, so `lab:list` and a hypothetical bare
    `list` are two different names rather than a collision. Flattening them would invent one.
    """
    found: dict[tuple[str, str], list[str]] = collections.defaultdict(list)

    def walk(resolver: URLResolver, prefix: str, namespace: str) -> None:
        for entry in resolver.url_patterns:
            route = prefix + str(entry.pattern)
            if isinstance(entry, URLResolver):
                walk(entry, route, namespace or entry.app_name or "")
            elif isinstance(entry, URLPattern) and entry.name:
                found[(namespace, entry.name)].append("/" + route)

    walk(get_resolver(), "", "")
    return found


class UrlNameTests(SimpleTestCase):
    """The two halves: that the walk found routes, and that none of them shares a name."""

    def test_the_walk_found_the_urlconf(self) -> None:
        """There are named routes to compare, which is the trap of every self-discovering check.

        A walk that stopped matching returns nothing, the comparison below succeeds over an empty
        mapping, and the demo is reported free of collisions without having been looked at. The
        floor is deliberately far below the real count — what is under test is that the reader
        works, not how many routes there happen to be today.
        """
        self.assertGreater(len(_names()), 40)

    def test_no_two_routes_claim_one_url_name(self) -> None:
        """One name, one route. The second claimant wins `reverse()` and nothing says so.

        The failure names both routes on purpose: which of the two a template meant is obvious from
        their paths, and the fix is always the same — the pages keep the bare name because they are
        what gets reversed, and the endpoint gains `_api`.
        """
        clashes = {
            f"{namespace}:{name}" if namespace else name: sorted(routes)
            for (namespace, name), routes in _names().items()
            if len(routes) > 1
        }

        self.assertEqual(
            clashes,
            {},
            f"these url names are claimed by more than one route: {clashes}. Django does not "
            f"complain — `reverse()` answers with the LAST one registered — so every `{{% url %}}` "
            f"in the demo now points at whichever of them the URLconf happens to include second. "
            f"Give the endpoint an `_api` suffix and leave the bare name to the page.",
        )
