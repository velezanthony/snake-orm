"""The session ANNOUNCES what the engine cannot do, and this is what makes that a fact in the demos.

`Cap` is the ORM's headline bargain: what an engine does not give, it DECLARES. A dialect answers the
whole catalogue with `Full()`, `Degraded(reason)` or `Nope(reason)`, forgetting one blows up at
import, and the session emits ONE warning per caveat this project is going to notice. The doctrine is
that the ORM never stores worse and stays quiet.

WHY THIS FILE EXISTS. That behaviour was verified NOWHERE across the four demo suites. Two of them
silenced `SnakeWarning` by CATEGORY, `pytest.warns` did not appear once in any of them, and mean-
while `shared/` genuinely CHANGES WHAT IT DOES depending on what the engine can do — a reservation
takes a real row lock or does not, a report is one statement or two. A showcase that behaves
differently per engine and never shows the user why is demonstrating the opposite of the bargain.

WHAT IS ASSERTED, and what is deliberately not. Re-deriving `_relevant_caveats` here would be a test
of the production code written twice, which passes by construction and proves nothing. So the three
properties below are each anchored to something OUTSIDE the warning machinery:

- Postgres stays QUIET. Zero caveats on the demo's primary engine, which is falsifiable the day a
  capability is downgraded and would otherwise be discovered by a user.
- Every capability THE DEMO'S OWN SOURCE branches on is announced when the engine lacks it. The list
  is read out of `shared/` by grepping for `supports_*` rather than typed here, so neither side of
  the comparison is a hand-kept list: the demo says what it cares about, the ORM says what it warns
  about, and this file checks they meet.
- Each caveat is announced ONCE. That is the half that makes the feature usable rather than merely
  present: nineteen lines a run is a tally somebody reads, and one per session is a flood somebody
  silences — which is exactly how this ended up silenced.

`pytest.warns` catches regardless of the filters in `pytest.ini`, so these assertions hold whatever a
future run decides to print.
"""

from __future__ import annotations

import pathlib
import re
import warnings

import pytest
from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    SnakeDialect,
    SnakeSession,
    SQLiteDialect,
)
from snakeorm.core.exceptions import SnakeWarning
from snakeorm.dialects.capabilities import Cap
from snakeorm.session import shared as session_module

import shared

_SHARED = pathlib.Path(shared.__file__).resolve().parent

# The three engines the demos are declared to run on, by the name their caveats are announced under.
_DIALECTS: tuple[tuple[str, SnakeDialect], ...] = (
    ("PostgresDialect", PostgresDialect()),
    ("MySQLDialect", MySQLDialect()),
    ("SQLiteDialect", SQLiteDialect()),
)


class _SilentDriver:
    """A driver that executes nothing. Opening a session emits the caveats before any statement."""

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        """Accepts and discards: this file is about what the session SAYS, not what it runs."""

    def commit(self) -> None:
        """Nothing was written, so there is nothing to commit."""

    def close(self) -> None:
        """Nothing was opened."""


def _announced(dialect: SnakeDialect, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The caveats a FRESH process would hear when this dialect's session opens.

    The tally the ORM keeps is global to the process — that is what makes each caveat arrive once
    rather than once per session — so it is reset first. Without that, whichever test ran earliest
    would have consumed the warnings and every assertion here would pass over an empty list, which
    is the vacuous-run shape this repository writes guards against.
    """
    monkeypatch.setattr(session_module, "_warned_caveats", set())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        SnakeSession(_SilentDriver(), dialect)  # type: ignore[arg-type]
    return [
        str(entry.message)
        for entry in caught
        if issubclass(entry.category, SnakeWarning)
    ]


def _capabilities_the_demo_branches_on() -> dict[str, Cap]:
    """The capabilities `shared/` READS, found in its own source rather than listed here.

    A `session.dialect.supports_x` in the domain layer is the demo saying "what I do depends on this",
    and that is the only reason a user has to be told about it. Reading them out of the tree is what
    keeps this test honest the day somebody adds a fourth branch: it joins the comparison by being
    written, not by being remembered.
    """
    found: dict[str, Cap] = {}
    for path in _SHARED.rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        for name in re.findall(r"supports_([a-z_]+)", path.read_text()):
            # The property and the catalogue entry are the same word in two spellings, which is a
            # contract of the dialect layer rather than a coincidence. If it ever stops holding, this
            # raises here instead of quietly dropping the capability out of the comparison.
            found[f"supports_{name}"] = Cap[name.upper()]
    return found


def test_the_scan_found_the_demo_adapting_to_the_engine() -> None:
    """That the source scan found capabilities at all, which is the trap of every self-discovering check.

    With an empty result the parametrised test below vanishes and the suite goes green over nothing.
    """
    assert _capabilities_the_demo_branches_on(), (
        f"no `supports_*` found under {_SHARED}: either the demo stopped adapting to the engine, or "
        f"this scan stopped being able to see that it does — and the two look identical from here."
    )


def test_postgres_has_nothing_to_declare(monkeypatch: pytest.MonkeyPatch) -> None:
    """The demo's primary engine opens in SILENCE, which is the other half of the bargain.

    A catalogue that warned about everything everywhere would be noise with a reason attached, and
    the first thing anybody does with noise is silence it — as these suites did. Postgres answering
    `Full` to all twenty-three is what makes the other two engines' warnings mean something.
    """
    assert _announced(PostgresDialect(), monkeypatch) == []


@pytest.mark.parametrize(
    "engine,dialect", _DIALECTS, ids=[name for name, _ in _DIALECTS]
)
def test_every_caveat_is_announced_once(
    engine: str, dialect: SnakeDialect, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No caveat is announced twice, and every announcement names its engine and the way out.

    Once is what makes the list readable. The message carries the engine because a process can open
    sessions onto two of them, and it carries the `filterwarnings` line because a developer who has
    one caveat under control has to be able to silence THAT one without silencing the other six.
    """
    announced = _announced(dialect, monkeypatch)

    assert len(announced) == len(set(announced)), (
        f"{engine} announced the same caveat twice: {announced}"
    )
    assert all(message.startswith(f"{engine}: ") for message in announced), announced
    assert all(
        "warnings.filterwarnings('ignore', category=SnakeWarning)" in message
        for message in announced
    ), announced


@pytest.mark.parametrize(
    "property_name,cap",
    sorted(_capabilities_the_demo_branches_on().items()),
    ids=[name for name in sorted(_capabilities_the_demo_branches_on())],
)
def test_the_engine_says_so_before_the_demo_behaves_differently(
    property_name: str, cap: Cap, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the demo CHANGES WHAT IT DOES because of a capability, the user was told about it first.

    This is the property that makes the warning worth emitting at all, and the only one here that
    ties the ORM's output to somebody's actual behaviour. `orders.reserve` takes a real row lock on
    two engines and none on the third; `order_report` is one statement on two and two on the third.
    Both differences are correct and both are invisible from the outside — the announcement is the
    only thing standing between "declared degradation" and "it quietly did something else".

    NOT FULL is the condition, not `can()`. A `Degraded` capability answers `can()` with YES — the
    model works, the value is exact — and still has something to say: what degrades is the SQL
    semantics. Reading the gate off `can()` would have skipped exactly the caveats a user most needs,
    which is the sort of thing this catalogue exists to keep out in the open.
    """
    for engine, dialect in _DIALECTS:
        reasons = dict(dialect.capabilities.caveats())
        announced = _announced(dialect, monkeypatch)
        if cap not in reasons:
            assert not any(
                cap.name.lower() in message.lower() for message in announced
            ), (
                f"{engine} answers Full to {cap.name} and warned about it anyway: {announced}"
            )
            continue
        assert any(reasons[cap] in message for message in announced), (
            f"`shared/` branches on `{property_name}`, {engine} does not answer Full to "
            f"{cap.name}, and the session never said so. What it announced was: {announced}"
        )
