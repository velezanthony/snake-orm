"""The capability catalogue, checked against the engines it describes.

`Cap` is the load-bearing declaration of this ORM: the plan stops on it, the session warns from it,
and the emitters skip on it. Everything downstream trusts it, and until now nothing asked whether it
was TRUE. A catalogue that says `Full` where the engine refuses breaks a query at runtime; one that
says `Nope` where the engine can do it hides a feature from every user of that engine. Both are
silent.

Every capability is asserted on every engine and NOTHING is skipped. Where the catalogue says the
engine can, the operation must succeed; where it says it cannot, the ORM itself must stop it. A
refusal that comes from the ENGINE means the ORM emitted SQL it should never have emitted; one that
comes from the CATALOGUE means the plan stopped where it was supposed to.

WRITING THIS FOUND SOMETHING, and the finding has since been ACTED ON rather than accommodated.
`Nope` used to mean two things: for `ROW_LOCKING` and `SET_ISOLATION` the ORM refuses, and for
`ILIKE` it emitted a working fallback and the query answered. This file carried a `_FALLS_BACK`
table so a test could hold the distinction the catalogue could not.

`ILIKE` is now `Degraded` and the shape it needs lives in `syntax.has_ilike`, so `Nope` means one
thing again — the ORM stops — and the table is gone. The branch it fed is gone with it: an engine
that declares `Nope` is expected to REFUSE, full stop, and this test says so without an exception
list. Worth keeping in view: a table written to hold a distinction is a good place to record one,
and a bad place to leave it.

The refusal's MESSAGE is deliberately not compared against the catalogue's `reason`: they are two
texts for one fact, and the message is written for whoever hit it. Asserting they match would force
the message to degrade into the reason.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.dialects.capabilities import Cap, Nope
from snakeorm.session.isolation import SnakeIsolation
from test.scenarios.engines import DIALECTS, three_sessions

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@snake_model(table="cap_people")
class Person(SnakeModel):
    """Somebody to lock, filter and read."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=50)


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three sessions with two people in them."""
    with three_sessions([Person]) as sessions:
        for session in sessions.values():
            session.add(Person(id=1, name="Ana"))
            session.add(Person(id=2, name="ana"))
            session.commit()
        yield sessions


def _use_ilike(session: SnakeSession) -> None:
    """Case-insensitive match: `Cap.ILIKE`."""
    session.all(SnakeQuery(Person).filter(Person.name.istartswith("ana")))


def _use_row_locking(session: SnakeSession) -> None:
    """`SELECT ... FOR UPDATE`: `Cap.ROW_LOCKING`."""
    session.all(SnakeQuery(Person).for_update())


def _use_set_isolation(session: SnakeSession) -> None:
    """`SET TRANSACTION ISOLATION LEVEL`: `Cap.SET_ISOLATION`."""
    session.set_isolation(SnakeIsolation.SERIALIZABLE)


def _named(cap: Cap) -> str:
    """The id of a parametrised capability. A named function and not a lambda: inside one, the
    parameter infers as `object` and the checker loses `Cap`."""
    return cap.name


_PROBES: dict[Cap, Callable[[SnakeSession], None]] = {
    Cap.ILIKE: _use_ilike,
    Cap.ROW_LOCKING: _use_row_locking,
    Cap.SET_ISOLATION: _use_set_isolation,
}
"""The capabilities reachable from a SESSION, and the smallest call that uses each.

Deliberately not every `Cap`: the DDL ones are already probed both ways by the emitter matrix, and
duplicating them here would be a second list to keep in step with the first.
"""

_REFUSAL_SAYS: dict[Cap, str] = {
    Cap.ROW_LOCKING: "row locking",
    Cap.SET_ISOLATION: "isolation level",
}
"""What the refusal has to SAY, per capability.

In this ORM the message is the product, so a `pytest.raises` that only checks the class is worth no
more than catching a bare `KeyError` — `test_messages_are_asserted` enforces exactly that and it is
the reason this table exists.

What is pinned is the PHRASE a user searches for, not the catalogue's `reason` word for word. Those
are two texts for one fact: the reason explains the engine, the message is written for whoever just
hit it. Asserting they match would drag the message down to the reason.
"""


_PROBE_ORDER: list[Cap] = [cap for cap in Cap if cap in _PROBES]
"""Walked from the enum rather than sorted by name: that gives the CATALOGUE's own order, which is
the order `caveats()` reports in, so a failure here and a warning at startup name things the same
way round."""


@pytest.mark.parametrize("engine", _ENGINES)
@pytest.mark.parametrize("cap", _PROBE_ORDER, ids=_named)
def test_the_catalogue_and_the_engine_agree(
    cap: Cap, engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Every capability, every engine, and NOTHING is skipped: each combination is asserted.

    Three outcomes and one test on purpose. Splitting it into a pair that skip each other's branch
    was the first shape, and it cost twelve skips whose reason was `can` — this repository leans on
    every skip saying `cannot`, so a skip that means "the other test covers it" quietly weakens the
    one property that makes a skipped suite readable.

    - **can** -> the call goes through, and the ENGINE accepts what the ORM emitted. This is the
      half that catches a `Full` that should be a `Nope`: the failure would come from the engine at
      runtime, to a user who read the catalogue and believed it.
    - **cannot** -> the ORM refuses, with `SnakeUnsupportedFeature` and a message that
      names the thing. That the exception is the ORM's and not the driver's is the load-bearing
      part: a refusal from the engine would mean SQL was emitted that never should have been.
    """
    support = DIALECTS[engine].capabilities.support_for(cap)
    session = engines[engine]

    if not isinstance(support, Nope):
        _PROBES[cap](session)
        return

    assert support.reason.strip(), f"{engine} refuses {cap.name} with an empty reason"

    with pytest.raises(SnakeUnsupportedFeature, match=_REFUSAL_SAYS[cap]):
        _PROBES[cap](session)


@pytest.mark.parametrize("engine", _ENGINES)
def test_every_probe_is_answered_one_way_or_the_other(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The sanity probe: a capability with no answer at all would slip through the branches above.

    `SnakeCapabilities` refuses to be built with one undeclared, so this cannot fail today. It is
    here because the test above READS the catalogue to decide what to assert, and a check that
    derives its own expectations needs one thing it does not derive.
    """
    unanswered = [
        cap.name
        for cap in _PROBE_ORDER
        if DIALECTS[engine].capabilities.support_for(cap) is None
    ]

    assert unanswered == [], f"{engine} answers for none of: {unanswered}"
