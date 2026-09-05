"""What a BRANCH of a set operation may carry, EXECUTED on the three engines.

`group_by()`, `having()` and `distinct()` are all legal SQL inside a branch and none of them had
ever been run through a compound. They part company on what the ORM does with them, and the two
answers are both right for different reasons:

- `group_by`/`having` never reach the engine. A compound's branch is compiled by the branch's own
  `to_sql`, which is the plain SELECT — and a plain SELECT does not EMIT a grouping, so it refuses
  rather than dropping the knob. The same refusal on the three, with the same words, because it is
  not a limitation of any engine.
- `distinct()` does reach it, and it means what it says on all three: it deduplicates its OWN
  branch, before the operator sees the rows. Which is only visible under `UNION ALL` — under
  `UNION` the set deduplicates afterwards anyway and a branch's `DISTINCT` cannot be seen at all.

The rows are seeded with a duplicate ON PURPOSE, because a `DISTINCT` over rows that are already
unique proves nothing and passes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from snakeorm import (
    SQLiteDialect,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
)
from snakeorm.core.exceptions import SnakeEmitError, SnakeUnsupportedFeature
from snakeorm.query.compound import SnakeCompoundBranch
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="branchclause_rows")
class BranchRow(SnakeModel):
    """No primary key of its own beyond `id`, so two rows can differ only in the id."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    tag: SnakeColumn[str] = snake_str(max_length=8)
    amount: SnakeColumn[int] = snake_int()


snake_link()

REFUSED = "refused"
"""What an engine answers when it will not express the query. It is not a wrong answer."""

# Rows 2 and 3 overlap the two halves below, so `UNION ALL` brings each of them TWICE.
_ROWS = ((1, "a", 100), (2, "b", 500), (3, "b", 500), (4, "c", 900))


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The THREE engines seeded. One missing is a skip: the comparison IS the test."""
    with three_sessions([BranchRow]) as sessions:
        for session in sessions.values():
            session.add_all([BranchRow(id=i, tag=t, amount=a) for i, t, a in _ROWS])
            session.commit()
        yield sessions


def _low() -> SnakeQuery[BranchRow]:
    """Rows 1, 2 and 3."""
    return SnakeQuery(BranchRow).filter(BranchRow.amount <= 500)


def _mid() -> SnakeQuery[BranchRow]:
    """Rows 2, 3 and 4."""
    return SnakeQuery(BranchRow).filter(BranchRow.amount >= 500)


def _answers(
    engines: dict[str, SnakeSession],
    build: Callable[[], SnakeCompoundBranch[BranchRow]],
) -> dict[str, list[int] | str]:
    """What each engine answers: the ids it returns, or `REFUSED` if it will not express it."""
    answers: dict[str, list[int] | str] = {}
    for name, session in engines.items():
        try:
            answers[name] = sorted(row.id for row in session.all(build()))
        except (SnakeEmitError, SnakeUnsupportedFeature):
            answers[name] = REFUSED
    return answers


@pytest.mark.parametrize("side", ["left", "right"])
def test_a_branch_that_groups_is_refused_on_the_three_engines(
    side: str, engines: dict[str, SnakeSession]
) -> None:
    """A `group_by()` in either branch is refused, and by the ORM rather than by any driver.

    The branch compiles through the plain SELECT, which does not emit a grouping. Dropping it would
    answer a different question in silence — one row per group asked for, every row handed back.
    """
    grouped = _low().group_by(BranchRow.tag)
    build = (
        (lambda: grouped.union(_mid()))
        if side == "left"
        else (lambda: _mid().union(grouped))
    )

    answers = _answers(engines, build)

    assert answers == {"sqlite": REFUSED, "postgres": REFUSED, "mysql": REFUSED}


def test_the_refusal_of_a_grouped_branch_names_the_knob_and_the_way_out() -> None:
    """The refusal is NAMED, so "everybody refused" above cannot be met by any old error.

    It has to say `group_by()` —the thing the caller typed— and where the grouping does belong.
    """
    with pytest.raises(SnakeUnsupportedFeature) as error:
        _low().group_by(BranchRow.tag).union(_mid()).to_sql(SQLiteDialect())

    message = str(error.value)
    assert "group_by()" in message and "select(...)" in message


def test_a_branch_that_filters_groups_is_refused_the_same_way(
    engines: dict[str, SnakeSession],
) -> None:
    """`having()` follows `group_by()`: it is a knob the plain SELECT carries and does not emit."""
    answers = _answers(
        engines, lambda: _low().having(BranchRow.amount > 1).union(_mid())
    )

    assert answers == {"sqlite": REFUSED, "postgres": REFUSED, "mysql": REFUSED}


def test_a_distinct_branch_deduplicates_itself_before_the_operator_sees_it(
    engines: dict[str, SnakeSession],
) -> None:
    """`distinct()` in a branch runs on the three and means the same on the three.

    Under `UNION ALL` rows 2 and 3 arrive twice — once per branch — and a `DISTINCT` on one branch
    does not change that: the two copies are in DIFFERENT branches, and `DISTINCT` only sees its
    own. That is exactly what has to be pinned down, because it is what a reader gets wrong.
    """
    plain = _answers(engines, lambda: _low().union_all(_mid()))
    with_distinct = _answers(engines, lambda: _low().distinct().union_all(_mid()))

    assert plain == {name: [1, 2, 2, 3, 3, 4] for name in plain}
    assert with_distinct == plain


def test_a_distinct_branch_is_invisible_under_a_union(
    engines: dict[str, SnakeSession],
) -> None:
    """Under `UNION` the set deduplicates afterwards, so the branch's `DISTINCT` changes nothing.

    Not a curiosity: it is the reason `distinct()` cannot be tested under `UNION` and has to be
    measured under `UNION ALL`. Pinned so a future `distinct` that quietly promoted the operator
    would be caught here.
    """
    plain = _answers(engines, lambda: _low().union(_mid()))
    with_distinct = _answers(
        engines, lambda: _low().distinct().union(_mid().distinct())
    )

    assert plain == {name: [1, 2, 3, 4] for name in plain}
    assert with_distinct == plain
