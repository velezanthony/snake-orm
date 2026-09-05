"""Set operations nested THREE deep, EXECUTED on the three engines, compared by ROWS.

`test_compound_nesting_matrix.py` measured two levels — `(a op b) op c` and `a op (b op c)` — and
found the regrouping SQLite does when it cannot parenthesise a branch. Two levels have only two
shapes; three have five, and three of them put a set in a position two levels never reach: a
compound as the LEFT branch of a compound that is itself a branch. That is where a refusal has to
travel UP through a node that was not asked about it.

Four sets that overlap PARTIALLY, so every association answers something different. Rows that all
say the same thing would let a regrouping pass unnoticed, which is the whole failure mode here.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
)
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.query.compound import SnakeCompoundBranch
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="deepnest_rows")
class DeepRow(SnakeModel):
    """Eight rows with a different value per column, so a swapped projection is VISIBLE."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    tag: SnakeColumn[str] = snake_str(max_length=8)
    amount: SnakeColumn[int] = snake_int()


snake_link()

REFUSED = "refused"
"""What an engine answers when it will not express the query. It is not a wrong answer."""

_OPERATORS = ("union", "union_all", "except_", "intersect")

# Four overlapping quarters of the same eight rows: no two of them are equal, none is contained in
# another, and every pair shares something. That is what makes the five shapes disagree.
_SETS = {
    "a": (1, 2, 3, 4),
    "b": (3, 4, 5, 6),
    "c": (5, 6, 7, 8),
    "d": (2, 4, 6, 8),
}


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The THREE engines seeded. One missing is a skip: the comparison IS the test."""
    with three_sessions([DeepRow]) as sessions:
        for session in sessions.values():
            session.add_all(
                [DeepRow(id=i, tag=f"t{i}", amount=i * 10) for i in range(1, 9)]
            )
            session.commit()
        yield sessions


def _rows(key: str) -> SnakeQuery[DeepRow]:
    """The query behind one of the four letters."""
    return SnakeQuery(DeepRow).filter(DeepRow.id.in_(list(_SETS[key])))


def _apply(
    left: SnakeCompoundBranch[DeepRow], name: str, right: SnakeCompoundBranch[DeepRow]
) -> SnakeCompoundBranch[DeepRow]:
    """`left <operator> right`, picking the operator by name."""
    operator: Callable[[SnakeCompoundBranch[DeepRow]], SnakeCompoundBranch[DeepRow]] = (
        getattr(left, name)
    )
    return operator(right)


# The FIVE ways of associating four operands. `((ab)c)d` is the plain chain; the other four each put
# a set in a position the two-level matrix never produced.
_SHAPES: dict[str, Callable[[str, str, str], SnakeCompoundBranch[DeepRow]]] = {
    "((ab)c)d": lambda x, y, z: _apply(
        _apply(_apply(_rows("a"), x, _rows("b")), y, _rows("c")), z, _rows("d")
    ),
    "(a(bc))d": lambda x, y, z: _apply(
        _apply(_rows("a"), y, _apply(_rows("b"), x, _rows("c"))), z, _rows("d")
    ),
    "(ab)(cd)": lambda x, y, z: _apply(
        _apply(_rows("a"), x, _rows("b")), y, _apply(_rows("c"), z, _rows("d"))
    ),
    "a((bc)d)": lambda x, y, z: _apply(
        _rows("a"), x, _apply(_apply(_rows("b"), y, _rows("c")), z, _rows("d"))
    ),
    "a(b(cd))": lambda x, y, z: _apply(
        _rows("a"), x, _apply(_rows("b"), y, _apply(_rows("c"), z, _rows("d")))
    ),
}

_TRIPLES = list(itertools.product(_OPERATORS, repeat=3))


def _answers(
    engines: dict[str, SnakeSession],
    build: Callable[[], SnakeCompoundBranch[DeepRow]],
) -> dict[str, list[int] | str]:
    """What each engine answers: the ids it returns, or `REFUSED` if it will not express it."""
    answers: dict[str, list[int] | str] = {}
    for name, session in engines.items():
        try:
            answers[name] = sorted(row.id for row in session.all(build()))
        except SnakeEmitError:
            answers[name] = REFUSED
    return answers


def _agree(answers: dict[str, list[int] | str]) -> bool:
    """Do the engines that DID answer all say the same thing? A refusal abstains."""
    given = [rows for rows in answers.values() if rows != REFUSED]
    return all(rows == given[0] for rows in given)


@pytest.mark.parametrize("shape", sorted(_SHAPES))
@pytest.mark.parametrize("operators", _TRIPLES, ids=lambda t: "-".join(t))
def test_three_level_nesting_never_answers_two_different_sets(
    shape: str, operators: tuple[str, str, str], engines: dict[str, SnakeSession]
) -> None:
    """Every association of four operands means the same on the three engines, or is REFUSED.

    The 320 combinations of five shapes and three operators. What must never happen is two engines
    answering two DIFFERENT sets: that is the shape the two-level matrix caught, and a third level
    is where a refusal has to be carried up by a node nobody asked about it.
    """
    answers = _answers(engines, lambda: _SHAPES[shape](*operators))

    assert _agree(answers), (
        f"{shape} with {operators} disagrees across engines: {answers}"
    )


def test_the_plain_left_chain_is_expressible_on_every_engine(
    engines: dict[str, SnakeSession],
) -> None:
    """`((a op b) op c) op d` never gets refused: left-to-right IS what the bare text says.

    The refusals below may not cost the ordinary chain. Written apart from the matrix so that a
    guard grown too wide fails HERE, naming the chain, instead of turning the matrix green by
    making everybody abstain.
    """
    for operators in _TRIPLES:
        answers = _answers(engines, lambda: _SHAPES["((ab)c)d"](*operators))
        assert REFUSED not in answers.values(), f"{operators}: {answers}"
        assert _agree(answers), f"{operators}: {answers}"


def test_a_set_nested_on_the_right_two_levels_down_is_refused_where_it_cannot_be_grouped(
    engines: dict[str, SnakeSession],
) -> None:
    """The refusal reaches THREE levels down, so the agreement above cannot be met by silence.

    `a EXCEPT (b UNION (c INTERSECT d))` has a set inside a set inside a branch. SQLite cannot
    parenthesise any of them and must refuse; the other two answer, and answer the same.
    """
    answers = _answers(
        engines,
        lambda: _rows("a").except_(_rows("b").union(_rows("c").intersect(_rows("d")))),
    )

    assert answers["sqlite"] == REFUSED
    assert answers["postgres"] == answers["mysql"] == [1, 2]
