"""`collection.first(...)`: one column of ONE related row, as a value.

`as_scalar()` cannot answer this: `SnakeSubquery` carries neither `LIMIT` nor `ORDER BY`, so a query
that asks for them has them dropped in silence. The correlation here comes from the relationship's
own foreign key, so it cannot be written wrong.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeUnknownColumn, SnakeUnsupportedFeature
from snakeorm.dialects import PostgresDialect
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Maker, Nation, Truck


def test_it_emits_a_correlated_subquery_with_a_limit() -> None:
    """The bare form: one column of one child row, correlated and limited to one."""
    snake_link()

    sql, params = SnakeQuery(Maker).to_project_sql(
        PostgresDialect(), [Maker.name, Maker.trucks.first(Truck.model)]
    )

    assert sql == (
        'SELECT "name", (SELECT e0."model" FROM "public"."trucks" AS e0 '
        'WHERE e0."maker_id" = "makers"."id" LIMIT %s) FROM "public"."makers"'
    )
    # The `1` is bound, not written: every LIMIT in this ORM goes through the dialect, which is
    # what keeps it portable across the three engines.
    assert params == (1,)


def test_the_order_decides_which_row_wins() -> None:
    """`order_by` decides which row wins, and it is emitted INSIDE the subquery."""
    snake_link()

    sql, _ = SnakeQuery(Maker).to_project_sql(
        PostgresDialect(),
        [Maker.trucks.first(Truck.model, order_by=(Truck.model.desc(),))],
    )

    assert 'ORDER BY e0."model" DESC LIMIT %s)' in sql


def test_a_condition_narrows_the_rows_it_chooses_from() -> None:
    """The optional condition lands in the subquery's WHERE, next to the correlation."""
    snake_link()

    sql, params = SnakeQuery(Maker).to_project_sql(
        PostgresDialect(), [Maker.trucks.first(Truck.model, Truck.model != "Ibiza")]
    )

    assert 'WHERE e0."maker_id" = "makers"."id" AND e0."model" <> %s LIMIT %s' in sql
    assert params == ("Ibiza", 1)


def test_the_projected_column_may_travel_through_the_child_to_one() -> None:
    """What is read may be a column of a to-one OF THE CHILD, joined inside the subquery.

    It is the shape the real call sites have: "the display name of the owner of the current
    contract". The JOIN machinery is the one `.any()` already uses for its condition.
    """
    snake_link()

    sql, _ = SnakeQuery(Nation).to_project_sql(
        PostgresDialect(), [Nation.makers.first(Maker.nation.name)]
    )

    assert 'FROM "public"."makers" AS e0' in sql
    assert 'JOIN "public"."nations" AS e1 ON e0."nation_id" = e1."id"' in sql
    assert 'SELECT e1."name"' in sql


def test_a_column_of_another_model_is_refused() -> None:
    """A column of neither the child nor a to-one of it fails LOUDLY.

    At runtime because it cannot be in the type: `SnakeExpr[T]` carries the value's type, not its
    owner.
    """
    snake_link()

    with pytest.raises(SnakeUnknownColumn) as caught:
        Nation.makers.first(Truck.model)

    assert "is not a column of the child model 'makers'" in str(caught.value)
    assert ".first()" in str(caught.value)


def test_a_bare_column_in_order_by_says_what_to_pass() -> None:
    """A column is not an ordering key, and the refusal names the fix instead of an attribute.

    It leaked `'SnakeExpr' object has no attribute 'expr'`, which reads as "ordering is not
    supported" — and somebody concluded exactly that. The type already says `SnakeOrder`; this is
    for whoever runs without a checker.
    """
    snake_link()

    with pytest.raises(SnakeUnsupportedFeature) as caught:
        # The checker refuses this too, which is the first line of defence; the ignore is what
        # lets the test reach the runtime one.
        Maker.trucks.first(Truck.model, order_by=(Truck.model,))  # type: ignore[arg-type]

    assert ".asc()" in str(caught.value)
    assert ".desc()" in str(caught.value)
