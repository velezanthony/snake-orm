"""Every GET this demo registers ANSWERS. Not "returns the right thing" — answers at all.

This file exists because of a measured failure, and the failure is the interesting part rather than
the fix. When the demo moved onto `AsyncSession`, five of the nine domains got an asynchronous twin
in `shared/aio/` and the dependency in `apps/deps.py` started handing an `AsyncSession` to ALL nine.
The four that had not been converted went on calling their synchronous use cases, so
`session.all(...)` handed them a coroutine and the endpoint died:

    TypeError: 'coroutine' object is not iterable       /api/content/posts/1/revisions
    RuntimeWarning: coroutine 'AsyncSession.all' was never awaited

And the suite reported **18 passed** the whole time, because those eighteen tests never touched
those domains. A count coming out full over a universe that had been trimmed is the exact shape of
failure this repository writes nets against, and here it was again, one storey up.

WHAT IT ASSERTS, AND WHY IT IS SO WEAK ON PURPOSE. Only that the status is under 500. A 404 is a
pass: these routes are walked with a made-up id and most of them will not find it, and demanding
otherwise would mean this file carrying a fixture per endpoint — a second suite, drifting from the
first. What a 500 means is that the handler RAISED, which is the one thing no endpoint may do and
the one thing the other eighteen tests did not look for.

It asks the app for its own OPENAPI document rather than reading a list of paths, and that is the
whole point: an endpoint added tomorrow is covered without anybody remembering to add it here. A
list is what has to be remembered, and the person who forgets is exactly the person the check was
written for.

The document and not `app.routes`, because `include_router` NESTS: on this version the nine routers
sit in `app.routes` as `_IncludedRouter` objects carrying no path of their own, so a walk that only
looked at the top level found ONE route and would have passed over almost nothing. The vacuous-run
guard below is what caught that, on the very first run of this file.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator

import pytest

os.environ.setdefault("SNAKE_ORM_DEBUG", "envelope,timing,sidecar")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

# A path parameter, as the OpenAPI document spells it: `/api/blog/posts/{post_id}`.
_PARAMETER = re.compile(r"\{[^{}]+\}")

# What FastAPI mounts for itself. They answer, and they answer without a session, so they prove
# nothing about the thing this file watches.
_NOT_A_DOMAIN = ("/openapi.json", "/docs", "/redoc")


def _gettable_paths() -> list[str]:
    """Every GET path the app declares it serves, with `1` standing in for each path parameter.

    One and not a seeded id: what is under test is that the handler RUNS, and a handler answering
    404 for an id that is not there has run. Picking real ids would mean knowing the seed here, and
    then this file would break every time the seeder changed — for a reason that has nothing to do
    with what it checks.
    """
    document = app.openapi()
    return sorted(
        {
            _PARAMETER.sub("1", path)
            for path, operations in document.get("paths", {}).items()
            if "get" in operations and path not in _NOT_A_DOMAIN
        }
    )


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """A client with the lifecycle active: `lifespan` creates the schema and seeds it on startup."""
    with TestClient(app) as test_client:
        yield test_client


def test_there_are_routes_to_walk() -> None:
    """The walk found routes. Without this, "nothing raised" would hold over an empty list.

    Nine routers are registered in `main.py`; a number well under that means the discovery broke and
    the file below is measuring nothing, which is precisely the state it was written to end.
    """
    paths = _gettable_paths()

    assert len(paths) >= 20, f"only {len(paths)} GET routes were found: {paths}"


@pytest.mark.parametrize("path", _gettable_paths(), ids=str)
def test_the_endpoint_answers_instead_of_raising(path: str, client: TestClient) -> None:
    """It answers with a status, whatever the status. A 500 means the handler raised.

    Reported one route per test so a failure names the route rather than handing over a list of
    forty paths with one bad entry somewhere in it.
    """
    response = client.get(path)

    assert response.status_code < 500, (
        f"{path} answered {response.status_code}. A 5xx here means the handler RAISED — the shape "
        f"this file exists for is a router still calling a synchronous use case with the "
        f"asynchronous session `apps/deps.py` now hands it."
    )
