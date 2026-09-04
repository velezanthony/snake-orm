"""Every GET this demo registers ANSWERS. Not "returns the right thing" — answers at all.

The twin of `django/apps/test_every_route_answers.py`, and it exists for the same measured reason:
the only net that walked routes read FastAPI's OpenAPI document, and neither SSR demo publishes one.
So when `/api/orders` arrived in these two, and again when the taxonomy pages did, the verification
that the routes answered at all was somebody starting the app and calling them BY HAND. A check that
depends on remembering is the check this repository writes nets to replace.

IT IS STRICTER THAN THE DJANGO TWIN, AND THE DIFFERENCE IS THE FRAMEWORK'S. A Flask rule declares its
methods, so this file walks only the rules that really accept a GET and a 405 is not something it has
to tolerate. Django's `path()` says nothing about verbs, so its twin walks everything and lets a 405
pass. Two nets asking the same question of two routers that answer it differently, rather than one
weakened until it fits both.

WHAT IT ASSERTS. Only that the status is under 500. A 404 is a pass: the rules are walked with a
made-up id and most will not find it, and demanding otherwise would mean a fixture per endpoint — a
second suite, drifting from the first. What a 500 means is that the handler RAISED.

IT READS `url_map` AND NOT A LIST. A route added tomorrow is covered without anybody coming here,
which is the whole point: a list is what has to be remembered, and the person who forgets is exactly
the person the check was written for.

AND IT DROPS NOTHING IN SILENCE. A rule whose converters this walk cannot fill is COLLECTED and named
by `test_every_rule_is_walkable` rather than skipped. A net that quietly covers less than it looks
like it covers is the exact shape of failure this file exists to end.

THIS FILE ONLY RUNS BECAUSE THE TARGET STOPPED NAMING ONE FILE. `make frameworks-test-flask` was
`pytest verify.py`, pinned to a single module — the same defect the Django target names in its own
comment, in its worse form, since a directory at least grows on its own and a filename does not. The
discovery now lives in `pytest.ini`, which keeps `verify.py` in the pattern so fixing the pin did not
cost the demo its existing suite.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient

from app import create_app

# A converter as Flask spells it inside a rule: `/taxonomy/detail/<int:post_id>`.
_CONVERTER = re.compile(r"<[^<>]+>")

# What Flask mounts for itself. It answers, and it answers without a session, so it proves nothing
# about the thing this file watches.
_NOT_A_DOMAIN = ("static",)

app = create_app()


def _walkable_and_not() -> tuple[list[str], list[str]]:
    """Every GET rule as `(walkable, unwalkable)`, with `1` standing in for each converter.

    One and not a seeded id: what is under test is that the handler RUNS, and a handler answering
    404 for an id that is not there has run. Picking real ids would mean knowing the seed here, and
    then this file would break every time the seeder changed — for a reason that has nothing to do
    with what it checks.
    """
    walkable: list[str] = []
    unwalkable: list[str] = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in _NOT_A_DOMAIN or "GET" not in (rule.methods or set()):
            continue
        path = _CONVERTER.sub("1", rule.rule)
        # A `path:` converter swallows slashes and anything left between angle brackets was never a
        # converter at all. Either way the substitution above did not produce a URL, and saying so
        # is the difference between a walk that covers less and a walk that hides it.
        if "<" in path or ">" in path:
            unwalkable.append(rule.rule)
        else:
            walkable.append(path)
    return sorted(set(walkable)), sorted(set(unwalkable))


_WALKABLE, _UNWALKABLE = _walkable_and_not()


@pytest.fixture(scope="module")
def client() -> Iterator[FlaskClient]:
    """One client for the whole walk: nothing here writes, so nothing needs a fresh database."""
    with app.test_client() as test_client:
        yield test_client


def test_there_are_rules_to_walk() -> None:
    """The walk found rules. Without this, "nothing raised" would hold over an empty list.

    Six page blueprints and nine JSON ones are registered in `app.py`, each carrying several rules; a
    number well under this means the discovery broke and the walk below is measuring nothing, which
    is precisely the state this file was written to end.
    """
    assert len(_WALKABLE) >= 40, (
        f"only {len(_WALKABLE)} GET rules were found: {_WALKABLE}"
    )


def test_every_rule_is_walkable() -> None:
    """Nothing is dropped in silence: a rule this walk cannot build a URL for is named.

    None exist today. If one appears — a `path:` converter, say — the honest outcome is this test
    going red with the rule in the message, not a walk that quietly covers one route fewer than the
    demo has.
    """
    assert _UNWALKABLE == [], (
        f"these rules cannot be walked and are therefore NOT covered: {_UNWALKABLE}. Give this file "
        f"a way to build them or the count above is measuring a universe smaller than the demo."
    )


@pytest.mark.parametrize("path", _WALKABLE, ids=str)
def test_the_route_answers_instead_of_raising(path: str, client: FlaskClient) -> None:
    """It answers with a status, whatever the status. A 500 means the handler raised.

    Reported one route per test so a failure names the route rather than handing over a list of
    sixty paths with one bad entry somewhere in it.
    """
    response = client.get(path)

    assert response.status_code < 500, (
        f"{path} answered {response.status_code}. A 5xx here means the handler RAISED, which is the "
        f"one thing no route may do — a 404 for a made-up id is an answer and passes."
    )
