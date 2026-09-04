"""The scalar expressions, EXECUTED on the three engines: does the value come back right?

These families were covered by tests that assert the emitted SQL STRING per dialect, which is a
different claim: the string can be exactly what the dialect intends and still be a function the
engine does not have. That is not a hypothesis — `ABS` and `ROUND` were missing from SQLite while
their string test was green, and `snake_round()` emitted a `ROUND(x, 0)` Postgres refuses.

So this one runs them and reads the values back. Text functions and the conditionals in one file
because they share a shape — an expression over a row, projected — and one seeded table serves both.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TypeVar

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeValue,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.expressions import (
    snake_case,
    snake_coalesce,
    snake_concat,
    snake_length,
    snake_lower,
    snake_nullif,
    snake_replace,
    snake_substring,
    snake_trim,
    snake_upper,
)
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="sx_labels")
class Label(SnakeModel):
    """Texts chosen so every function has something to change."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    nickname: SnakeColumn[str | None] = snake_str()
    rank: SnakeColumn[int] = snake_int()


_ROWS = [
    (1, "  Ada Lovelace  ", None, 10),
    (2, "Grace Hopper", "Amazing Grace", 20),
]


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with the same two rows. One missing is a skip: the comparison IS the test."""
    with three_sessions([Label]) as sessions:
        for session in sessions.values():
            session.add_all(
                [Label(id=i, name=n, nickname=k, rank=r) for i, n, k, r in _ROWS]
            )
            session.commit()
        yield sessions


_T = TypeVar("_T")


def _one(session: SnakeSession, expression: SnakeValue[_T], row_id: int = 1) -> _T:
    """Project one expression over one row and hand back the value the engine returned."""
    rows = session.select(SnakeQuery(Label).filter(Label.id == row_id), expression)
    return rows[0][0]


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_the_case_functions_agree_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`LOWER` and `UPPER` return the same text on the three."""
    session = engines[engine]

    assert _one(session, snake_lower(Label.name), 2) == "grace hopper"
    assert _one(session, snake_upper(Label.name), 2) == "GRACE HOPPER"


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_trim_and_length_agree_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`TRIM` drops the padding and `LENGTH` counts CHARACTERS, which is not what MySQL's does.

    Row 1 is padded on purpose: a `LENGTH` over the untrimmed value would count the spaces too, and
    the point of pairing them is that the ORM's `LENGTH` is `CHAR_LENGTH` on MySQL — bytes there
    would be the same number for ASCII and a different one the day a name carries an accent.
    """
    session = engines[engine]

    assert _one(session, snake_trim(Label.name)) == "Ada Lovelace"
    assert _one(session, snake_length(snake_trim(Label.name))) == len("Ada Lovelace")


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_substring_replace_and_concat_agree_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The three that spell differently per engine: `SUBSTRING`, `REPLACE` and `CONCAT`."""
    session = engines[engine]

    assert _one(session, snake_substring(Label.name, 1, 5), 2) == "Grace"
    assert (
        _one(session, snake_replace(Label.name, "Hopper", "Murray"), 2)
        == "Grace Murray"
    )
    assert _one(session, snake_concat(Label.name, " (n/a)"), 2) == "Grace Hopper (n/a)"


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_case_picks_the_first_branch_that_matches_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`CASE WHEN` takes the FIRST branch that matches, and falls to the default when none does.

    Both rows are asked with the same expression: one that lands on a branch and one that reaches
    the default. Asking only the branch would pass on an engine that ignored the default entirely.
    """
    session = engines[engine]
    grade = snake_case(
        (Label.rank < 15, "junior"),
        (Label.rank < 25, "senior"),
        default="unknown",
    )

    assert _one(session, grade, 1) == "junior"
    assert _one(session, grade, 2) == "senior"
    assert _one(
        session, snake_case((Label.rank > 99, "impossible"), default="fell-through"), 1
    ) == ("fell-through")


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_coalesce_answers_the_fallback_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`COALESCE` over a NULL column returns the fallback, and over a filled one the value."""
    session = engines[engine]

    assert _one(session, snake_coalesce(Label.nickname, Label.name), 1) == (
        "  Ada Lovelace  "
    )
    assert (
        _one(session, snake_coalesce(Label.nickname, Label.name), 2) == "Amazing Grace"
    )


@pytest.mark.parametrize("engine", ["postgres", "mysql", "sqlite"])
def test_nullif_blanks_the_match_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`NULLIF` returns NULL when the two sides are equal, and the value when they are not."""
    session = engines[engine]

    assert _one(session, snake_nullif(Label.rank, 20), 2) is None
    assert _one(session, snake_nullif(Label.rank, 99), 2) == 20
