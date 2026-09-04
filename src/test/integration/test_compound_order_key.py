"""The `ORDER BY` of a set, EXECUTED on the three engines: does it sort by what the caller named?

A compound's `ORDER BY` is written against the RESULT of the set, and a result is not a table: there
is no alias to qualify with and nothing to JOIN to. The emitter knew that — it passes
`qualify=None` — and nothing checked that the key could survive it. Two shapes got through:

- A key over a RELATIONSHIP (`OrderKeyTicket.brand.name`) lost the hop and came out as the bare
  `"name"`. On a model that owns a `name` of its own that is a DIFFERENT column, the SQL is valid,
  and the three engines sort the same wrong way. Comparing engines cannot find that — they all
  agree. The only witness is what the SAME key means on a plain query, where the JOIN does get built.
- A key naming a column the branches do not PROJECT. Here nobody agreed on anything: SQLite said
  `1st ORDER BY term does not match any column in the result set`, Postgres `column "amount" does
  not exist` and MySQL `1054`. Three drivers explaining a decision the ORM made.

The models carry a deliberate name collision, because that is what makes the first one silent
instead of loud.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SnakeToOne,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
    snake_to_one,
)
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.query.compound import SnakeCompoundBranch
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="ordkey_brands")
class OrderKeyBrand(SnakeModel):
    """The far end of the hop. Its `name` sorts the OPPOSITE way to the ticket's own."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=20)


@snake_model(table="ordkey_tickets")
class OrderKeyTicket(SnakeModel):
    """A `name` of its own, colliding with the brand's: that is what makes the bug silent."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=20)
    amount: SnakeColumn[int] = snake_int()
    brand_id: SnakeColumn[int] = snake_int()
    brand: SnakeToOne[OrderKeyBrand] = snake_to_one(brand_id)


snake_link()

REFUSED = "refused"
"""What an engine answers when it will not express the query. It is not a wrong answer."""

# The two orderings point OPPOSITE ways: by the ticket's own name it is 1, 2; by the brand's, 2, 1.
_BRANDS = ((1, "zulu"), (2, "alfa"))
_TICKETS = ((1, "alfa-ticket", 100, 1), (2, "zulu-ticket", 900, 2))


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The THREE engines with both tables seeded. One missing is a skip: the comparison IS the test."""
    with three_sessions([OrderKeyBrand, OrderKeyTicket]) as sessions:
        for session in sessions.values():
            session.add_all([OrderKeyBrand(id=i, name=n) for i, n in _BRANDS])
            session.commit()
            session.add_all(
                [
                    OrderKeyTicket(id=i, name=n, amount=a, brand_id=b)
                    for i, n, a, b in _TICKETS
                ]
            )
            session.commit()
        yield sessions


def _cheap() -> SnakeQuery[OrderKeyTicket]:
    """Ticket 1."""
    return SnakeQuery(OrderKeyTicket).filter(OrderKeyTicket.amount < 500)


def _dear() -> SnakeQuery[OrderKeyTicket]:
    """Ticket 2."""
    return SnakeQuery(OrderKeyTicket).filter(OrderKeyTicket.amount > 500)


def _narrowed_set_ordered_by_a_missing_column() -> SnakeCompoundBranch[OrderKeyTicket]:
    """`only(name)` on both branches, then `order_by(amount)`: the column is not in the result."""
    return (
        _cheap()
        .only(OrderKeyTicket.name)
        .union(_dear().only(OrderKeyTicket.name))
        .order_by(OrderKeyTicket.amount)
    )


def _answers(
    engines: dict[str, SnakeSession],
    build: Callable[[], SnakeCompoundBranch[OrderKeyTicket]],
) -> dict[str, list[int] | str]:
    """The ids each engine returns IN ORDER, or `REFUSED` if it will not express the query."""
    answers: dict[str, list[int] | str] = {}
    for name, session in engines.items():
        try:
            answers[name] = [row.id for row in session.all(build())]
        except SnakeEmitError:
            answers[name] = REFUSED
    return answers


def test_a_set_orders_by_a_projected_column_on_the_three_engines(
    engines: dict[str, SnakeSession],
) -> None:
    """The ordinary case still answers, so the two refusals below cannot be a blanket ban.

    Ordering the SET is the whole point of `.order_by()` on a compound, and the three engines have
    to give the same order back.
    """
    answers = _answers(
        engines, lambda: _cheap().union(_dear()).order_by(OrderKeyTicket.name.desc())
    )

    assert answers == {"sqlite": [2, 1], "postgres": [2, 1], "mysql": [2, 1]}


def test_a_set_never_sorts_by_a_column_the_caller_did_not_name(
    engines: dict[str, SnakeSession],
) -> None:
    """The compound answers what the PLAIN query answers for that key, or it refuses.

    This is the comparison that catches it, and cross-engine agreement is not: the ORM emitted the
    same wrong `ORDER BY "name"` everywhere, so all three agreed. What the key MEANS is settled by
    the plain query, which does build the JOIN — and there the answer is [2, 1].
    """
    plain = {
        name: [
            row.id
            for row in session.all(
                SnakeQuery(OrderKeyTicket).order_by(OrderKeyTicket.brand.name)
            )
        ]
        for name, session in engines.items()
    }
    assert plain == {"sqlite": [2, 1], "postgres": [2, 1], "mysql": [2, 1]}

    answers = _answers(
        engines, lambda: _cheap().union(_dear()).order_by(OrderKeyTicket.brand.name)
    )

    for name, rows in answers.items():
        assert rows == REFUSED or rows == plain[name], (
            f"{name} sorted a set by a different column than the plain query does: {answers}"
        )


def test_ordering_a_set_by_a_relationship_is_refused_and_says_which_key(
    engines: dict[str, SnakeSession],
) -> None:
    """The refusal is NAMED, so the agreement above cannot be met by everybody staying silent.

    The key needs a JOIN and the result of a set has no table to join to, so it is refused on the
    three: this is not a limitation of any engine. The message names the key the caller typed.
    """
    with pytest.raises(SnakeEmitError) as error:
        _cheap().union(_dear()).order_by(OrderKeyTicket.brand.name)

    assert "brand.name" in str(error.value)

    answers = _answers(
        engines, lambda: _cheap().union(_dear()).order_by(OrderKeyTicket.brand.name)
    )
    assert answers == {"sqlite": REFUSED, "postgres": REFUSED, "mysql": REFUSED}


def test_ordering_a_set_by_a_column_the_branches_do_not_project_is_refused(
    engines: dict[str, SnakeSession],
) -> None:
    """A narrowed set cannot be ordered by a column it left out, and the ORM says so, not the driver.

    With `only(name)` on both branches the result carries `id` and `name` and nothing else, so
    `amount` is not there to sort by. Three engines used to answer three native errors, none of
    them mentioning `only()`.
    """
    with pytest.raises(SnakeEmitError) as error:
        _narrowed_set_ordered_by_a_missing_column()

    message = str(error.value)
    assert "amount" in message and "only()" in message

    for session in engines.values():
        with pytest.raises(SnakeEmitError, match="only\\(\\)/defer\\(\\)"):
            session.all(_narrowed_set_ordered_by_a_missing_column())
