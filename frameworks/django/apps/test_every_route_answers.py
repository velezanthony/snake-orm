"""Every route this demo registers ANSWERS. Not "returns the right thing" — answers at all.

The FastAPI demo has had this net since its routers went asynchronous, and the two SSR demos have
not. That asymmetry was not a gap somebody had not got round to: it was the thing that made a
measured failure possible, twice.

WHAT IT COST, MEASURED. When `/api/orders` was added to Django and Flask, the verification that
caught `POST /api/orders` blowing up without a trailing slash was somebody starting the app and
calling the endpoints BY HAND — because the only net that walks routes reads FastAPI's OpenAPI
document, and neither of the other two publishes one. Twenty-eight routes had been declared and not
one of them called. The same thing happened again with the taxonomy pages: ten routes across the two
demos, verified by hand, by remembering. A check that depends on somebody remembering is the check
this repository writes nets to replace.

WHAT IT ASSERTS, AND WHY IT IS SO WEAK ON PURPOSE. Only that the status is under 500. A 404 is a
pass: these routes are walked with a made-up id and most of them will not find it, and demanding
otherwise would mean a fixture per endpoint — a second suite, drifting from the first. A 405 is a
pass too, and that one is worth saying out loud: Django does not declare methods on a route, so a
POST-only view is walked with a GET and answers "not that verb". It ran, which is what is under
test. What a 500 means is that the handler RAISED.

AND THE STATUS ASSERTION IS THE SECOND NET, NOT THE FIRST. Django's test client re-raises whatever
the view raised instead of turning it into a 500 page, so a raising handler arrives here as an ERROR
carrying the traceback and the line — which is more useful than a bare status and is what verifying
this file by mutation actually produced. The `assertLess` below catches the other half: a middleware
or a handler that swallows the exception and returns a 5xx of its own, where there is no traceback
to read and the status is the only thing that says anything happened.

IT READS THE URLCONF AND NOT A LIST. A route added tomorrow is covered without anybody remembering
to come here, which is the whole point: a list is what has to be remembered, and the person who
forgets is exactly the person the check was written for.

AND IT DROPS NOTHING IN SILENCE. `path()` routes turn into a walkable path by substituting the
converters; a `re_path()` cannot, and rather than skipping those quietly the walk collects them and
`test_every_route_is_walkable` fails naming them. A net that silently covers less than it looks like
it covers is the exact shape of failure this file exists to end.

`SimpleTestCase`: the business data does NOT touch Django's ORM; SnakeORM carries it.
"""

from __future__ import annotations


import re
from typing import Literal

from django.test import Client, SimpleTestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver

from apps.blog import seed

# A `path()` converter as Django spells it inside a route: `detail/<int:post_id>/`.
_CONVERTER = re.compile(r"<[^<>]+>")

# What a walkable path may still contain once the converters are gone. Anything else means the route
# came from a `re_path()` and carries a regex this walk cannot turn into a URL.
_REGEX_METACHARACTERS = set(r"^$*+?[]()|\\")


def _routes() -> tuple[list[str], list[str]]:
    """Every route in the URLconf as `(walkable, unwalkable)`, with `1` for each converter.

    One and not a seeded id: what is under test is that the handler RUNS, and a handler answering
    404 for an id that is not there has run. Picking real ids would mean knowing the seed here, and
    then this file would break every time the seeder changed — for a reason that has nothing to do
    with what it checks.
    """
    walkable: list[str] = []
    unwalkable: list[str] = []

    def walk(resolver: URLResolver, prefix: str) -> None:
        for entry in resolver.url_patterns:
            route = prefix + str(entry.pattern)
            if isinstance(entry, URLResolver):
                walk(entry, route)
            elif isinstance(entry, URLPattern):
                path = _CONVERTER.sub("1", route)
                if set(path) & _REGEX_METACHARACTERS:
                    unwalkable.append(route)
                else:
                    walkable.append("/" + path)

    walk(get_resolver(), "")
    return sorted(set(walkable)), sorted(set(unwalkable))


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"])
class EveryRouteAnswersTests(SimpleTestCase):
    """The whole URLconf, walked with a GET, asserting only that nothing raised."""

    databases: set[str] | Literal["__all__"] = set()

    def setUp(self) -> None:
        """Leaves the SnakeORM database in its seeded state before the walk."""
        seed.reset_and_seed()
        self.client = Client()

    def test_there_are_routes_to_walk(self) -> None:
        """The walk found routes. Without this, "nothing raised" would hold over an empty list.

        Fourteen includes are registered in `config/urls.py` and each carries several routes; a
        number well under this means the discovery broke and the walk below is measuring nothing,
        which is precisely the state this file was written to end.
        """
        walkable, _ = _routes()

        self.assertGreaterEqual(
            len(walkable), 60, f"only {len(walkable)} routes were found: {walkable}"
        )

    def test_every_route_is_walkable(self) -> None:
        """Nothing is dropped in silence: a route this walk cannot build a URL for is named.

        `re_path()` routes carry a regex instead of converters and cannot be turned into a path. None
        exist today. If one appears, the honest outcome is this test going red with its name in the
        message — not a walk that quietly covers one route fewer than the demo has.
        """
        _, unwalkable = _routes()

        self.assertEqual(
            unwalkable,
            [],
            f"these routes cannot be walked and are therefore NOT covered: {unwalkable}. "
            f"They come from a `re_path()`; give this file a way to build them or the count above "
            f"is measuring a universe smaller than the demo.",
        )

    def test_the_route_answers_instead_of_raising(self) -> None:
        """Every route answers with a status, whatever the status. A 500 means the handler raised.

        `subTest` per route so a failure names the route rather than handing over a list of eighty
        paths with one bad entry somewhere in it.
        """
        walkable, _ = _routes()
        for path in walkable:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertLess(
                    response.status_code,
                    500,
                    f"{path} answered {response.status_code}. A 5xx here means the handler RAISED, "
                    f"which is the one thing no route may do — a 404 for a made-up id and a 405 for "
                    f"the wrong verb are both answers and both pass.",
                )
