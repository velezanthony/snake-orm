"""INTEGRATION: the operators against the THREE engines, above all the ESCAPING.

Escaping wildcards is the one thing in this batch that cannot be taken on trust: it has to be
checked that Postgres treats the backslash as an escape inside `LIKE`. If it did not,
`startswith("100%")` would bring back extra rows and NOBODY would notice —it does not fail, it just
returns rubbish—.

Case sensitivity is the one thing here the three do NOT share, and it is handled by asking the
catalogue instead of by picking a winner: Postgres has `ILIKE`, MySQL's `LIKE` is already
case-insensitive by the column's collation, and SQLite's folds ASCII only. That is declared in
`Cap.ILIKE`, so the case test runs where the engine can answer it and a companion asserts the
declaration on the other two.

Skipped gracefully when an engine is not reachable.
"""

from __future__ import annotations

from collections.abc import Iterator

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
from snakeorm.dialects.capabilities import Cap, Degraded
from test.scenarios.engines import DIALECTS, three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="op_labels")
class Label(SnakeModel):
    """Labels whose texts were picked to catch the escaping out."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    text: SnakeColumn[str] = snake_str(max_length=50)
    score: SnakeColumn[int] = snake_int()


_ROWS = [
    (1, "100% algodón", 10),
    (2, "100 per cent", 20),
    (3, "Ana Pérez", 30),
    (4, "ana minúscula", 40),
    (5, "a_b literal", 50),
    (6, "axb comodín", 60),
]


_ENGINES = ["postgres", "mysql", "sqlite"]


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with the same six labels."""
    with three_sessions([Label]) as sessions:
        for session in sessions.values():
            session.add_all([Label(id=i, text=x, score=s) for i, x, s in _ROWS])
            session.commit()
        yield sessions


def _ids(session: SnakeSession, condition: object) -> list[int]:
    """The ids the filter returns, sorted."""
    rows = session.all(SnakeQuery(Label).filter(condition))  # type: ignore[arg-type]
    return sorted(label.id for label in rows)


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_percent_in_the_value_is_data_not_a_wildcard(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """THE SHARP CASE: `startswith("100%")` must NOT bring back "100 per cent".

    Left unescaped, the `%` would be a wildcard and both rows would match. The filter would return
    too much, and silently, which is exactly the failure this test exists to prevent.
    """
    assert _ids(engines[engine], Label.text.startswith("100%")) == [1]


@pytest.mark.parametrize("engine", _ENGINES)
def test_an_underscore_in_the_value_is_data_too(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Checks the same thing with `_`, which in SQL matches ANY single character."""
    assert _ids(engines[engine], Label.text.contains("a_b")) == [5]


@pytest.mark.parametrize("engine", _ENGINES)
def test_contains_still_matches_as_a_substring(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Checks that escaping does not break the normal substring-search behaviour."""
    assert _ids(engines[engine], Label.text.contains("per cent")) == [2]


def test_ilike_ignores_case_and_like_does_not(
    engines: dict[str, SnakeSession],
) -> None:
    """The difference between the two variants, on the ONE engine whose `LIKE` is case-sensitive.

    Running this on the other two would not be a stricter test, it would be a wrong one: their
    `LIKE` already ignores case, so `startswith("Ana")` legitimately returns both rows there. That
    is a declared capability, and the test below reads it from the catalogue rather than from here.
    """
    session = engines["postgres"]

    assert _ids(session, Label.text.startswith("Ana")) == [3]
    assert _ids(session, Label.text.istartswith("ana")) == [3, 4]


@pytest.mark.parametrize("engine", ["mysql", "sqlite"])
def test_the_engines_without_ilike_say_so_in_the_catalogue(engine: str) -> None:
    """The other half of the test above: the caveat is DECLARED, not merely skipped.

    `Degraded` and not `Nope`, and the word is the point. These two engines DO answer a
    case-insensitive match — the emitter writes `LOWER(a) LIKE LOWER(b)` — so nothing is refused and
    no plan stops. What is weaker is the folding, which is what `Degraded` is for. It read `Nope`
    while the query worked, and that is how one word came to mean two things.
    """
    support = DIALECTS[engine].capabilities.support_for(Cap.ILIKE)

    assert isinstance(support, Degraded), (
        f"{engine} should degrade ILIKE, not {support}"
    )
    assert support.reason.strip(), f"{engine} degrades ILIKE without saying why"


@pytest.mark.parametrize("engine", _ENGINES)
def test_between_is_inclusive_on_both_ends(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Checks the range includes both ends: it is what anyone writing it expects it to do."""
    assert _ids(engines[engine], Label.score.between(20, 40)) == [2, 3, 4]


@pytest.mark.parametrize("engine", _ENGINES)
def test_not_in_excludes_exactly_what_it_says(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Checks that `not_in` leaves out the given values and NOTHING else."""
    assert _ids(engines[engine], Label.id.not_in([1, 2, 3])) == [4, 5, 6]


@pytest.mark.parametrize("engine", _ENGINES)
def test_endswith_anchors_at_the_end(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Checks the wildcard is anchored at the start."""
    assert _ids(engines[engine], Label.text.endswith("algodón")) == [1]
