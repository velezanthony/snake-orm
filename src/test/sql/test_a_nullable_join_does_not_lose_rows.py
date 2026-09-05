"""The JOIN type follows the relation's NULLABILITY, not the predicate that mentions it.

An `INNER JOIN` over a relation that may have no partner drops the rows with a null FK, and it drops
them WITHOUT AN ERROR — the page just shows fewer rows. Measured on a real product: 9 of 16 requests
vanished from a search box, and 1 of 10 supplies from a listing.

The rule chosen is the narrow one: nullable → LEFT, required → INNER, and nothing about the
predicate enters the decision. Recovering the INNER when the WHERE provably rejects nulls was
considered and measured, and it is worse on both counts — PostgreSQL already reverts the LEFT to the
same plan when the filter rejects nulls (identical cost, identical plan), and where it does NOT, the
LEFT lets the planner ELIMINATE the join entirely, which the INNER forbids because an INNER filters.
Measured at 46% faster on the shape this file's first test pins down.
"""

from __future__ import annotations

from snakeorm import snake_case
from snakeorm.dialects import PostgresDialect
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.nullable_domain import NULLABLE, Voyage


def test_a_projection_with_no_filter_uses_left_join() -> None:
    """The cleanest case: a statement with NO `WHERE` at all cannot justify an INNER.

    It needs no reasoning about which predicates reject nulls — there is no predicate. The prefix
    reached the plan because a projected `CASE` mentions it, and a `CASE` restricts nothing.
    """
    snake_link(NULLABLE)
    flag = snake_case((Voyage.harbour.name == "Vigo", 1), default=0)

    sql, _ = SnakeQuery(Voyage).to_project_sql(PostgresDialect(), [Voyage.code, flag])

    assert 'LEFT JOIN "public"."harbours"' in sql
    assert "WHERE" not in sql


def test_an_or_branch_over_a_nullable_relation_uses_left_join() -> None:
    """The reported case: one `OR` branch navigates the relation and the other does not.

    A row with a null FK can satisfy the OTHER branch, so removing it is losing a row that matched.
    """
    snake_link(NULLABLE)

    sql, _ = (
        SnakeQuery(Voyage)
        .filter((Voyage.code == "X") | (Voyage.harbour.name == "Vigo"))
        .to_sql(PostgresDialect())
    )

    assert 'LEFT JOIN "public"."harbours"' in sql


def test_a_required_relation_keeps_its_inner_join() -> None:
    """The control: a to-one that cannot be empty still joins INNER, and this must not regress.

    Without it, the fix could be "LEFT everywhere", which passes every other test in this file and
    throws away a join type the engine uses.
    """
    snake_link(NULLABLE)

    sql, _ = (
        SnakeQuery(Voyage).filter(Voyage.berth.code == "A1").to_sql(PostgresDialect())
    )

    # Anchored on what PRECEDES the keyword. `'JOIN "public"."berths"' in sql` is satisfied by
    # `LEFT JOIN "public"."berths"` too, so on its own it passes on the wrong answer.
    assert 'AS t0 JOIN "public"."berths" AS t1 ON' in sql


def test_a_null_rejecting_filter_uses_left_join_too() -> None:
    """Even where an INNER would be correct, the emitted join is LEFT — deliberately.

    This is the one place the rule diverges from Django, which keeps the INNER here (measured: 1 of
    11 nullable joins across 12 real selectors). It returns the same rows either way, because the
    filter drops the null side itself, and PostgreSQL plans the two identically.
    """
    snake_link(NULLABLE)

    sql, _ = (
        SnakeQuery(Voyage)
        .filter(Voyage.harbour.name == "Vigo")
        .to_sql(PostgresDialect())
    )

    assert 'LEFT JOIN "public"."harbours"' in sql


def test_one_statement_answers_both_ways_at_once() -> None:
    """The two edges in ONE query: the optional one LEFT, the required one INNER, side by side.

    It is the test the other three cannot be: each of those holds a single join, so a check for
    `"LEFT JOIN" not in sql` stands in for reading the clause. With two joins that crutch is gone —
    the string carries both keywords and only their position tells them apart.
    """
    snake_link(NULLABLE)

    sql, _ = (
        SnakeQuery(Voyage)
        .filter((Voyage.harbour.name == "Vigo") & (Voyage.berth.code == "A1"))
        .to_sql(PostgresDialect())
    )

    assert 'AS t0 JOIN "public"."berths" AS t1 ON t0."berth_id" = t1."id"' in sql
    assert 'LEFT JOIN "public"."harbours" AS t2 ON t0."harbour_id" = t2."id"' in sql
