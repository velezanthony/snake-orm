"""Ordering by a correlated aggregate: the ORDER BY gets the same correlation as the projection.

`emit_project` says it in its own comment — "one single correlation for the whole statement" — and
then hands it to the projection, to the GROUP BY and to the HAVING, and not to the ORDER BY. So a
correlated aggregate that projects perfectly raises `SnakeSubqueryAggregate without a correlation
context` the moment it is also used to sort by, which is the natural next thing to want:

    session.annotate(SnakeQuery(Nation), NationStats, maker_count=Nation.makers.count())   # works
    ... .order_by(Nation.makers.count().desc())                                            # raised

WHERE IT SHOWED UP. In `frameworks/`, ordering warehouses by the units they hold. The aggregate was
already projected in the same statement, so the subquery the ORDER BY needed was being emitted a few
characters earlier in the very same SQL.

THE SHAPE OF THE DEFECT, which this repository has now met several times: a rule stated for the
WHOLE of something and then applied to all but one of its parts. The comment was right and the code
was one argument short of it.
"""

from __future__ import annotations

import pytest

from snakeorm.decorators import SnakeResult, snake_result
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.expressions.functions import count
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Maker, Nation

# The relations have to be linked BEFORE a query is built with one: `Nation.makers` is a descriptor
# that resolves through the graph, so an unlinked registry refuses at ATTRIBUTE ACCESS, not at
# emission.
snake_link()


@snake_result
class _NationStats(SnakeResult[Nation]):
    """A nation and how many makers it holds."""

    nation: Nation
    maker_count: int


def _annotate_sql(query: SnakeQuery[Nation], dialect: object) -> str:
    """The SQL `annotate` would run for that query, with the maker count as its scalar."""
    sql, _ = query.to_annotate_sql(dialect, (Nation.makers.count(),))  # type: ignore[arg-type]
    return sql


def test_ordering_by_a_projected_aggregate_emits_the_correlated_subquery() -> None:
    """The whole point: the ORDER BY carries the same correlated subquery as the projection.

    Emitted rather than described, because the correlation is what the defect was about: the alias
    of the child and the reference back to the parent both have to be there.
    """
    query = SnakeQuery(Nation).order_by(Nation.makers.count().desc())

    sql = _annotate_sql(query, PostgresDialect())

    assert sql.startswith(
        'SELECT "id", "name", (SELECT COUNT(*) FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id")'
    ), sql
    # `e1` and not `e0`: the two subqueries are separate scopes and could reuse the name, but the
    # alias counter runs across the whole statement. Distinct aliases cost nothing and remove the
    # one question a reader would otherwise have to answer to be sure they are two subqueries.
    assert sql.endswith(
        'ORDER BY (SELECT COUNT(*) FROM "public"."makers" AS e1 '
        'WHERE e1."nation_id" = "nations"."id") DESC'
    ), sql


@pytest.mark.parametrize(
    "dialect",
    [PostgresDialect(), MySQLDialect(), SQLiteDialect()],
    ids=["postgres", "mysql", "sqlite"],
)
def test_it_works_on_the_three_engines(dialect: object) -> None:
    """A correlated subquery in an ORDER BY is plain SQL, so no engine needs an exception.

    This is checked because the fix could have been written as one engine's, and it is not: nothing
    in it depends on a capability. Only the quoting changes.
    """
    query = SnakeQuery(Nation).order_by(Nation.makers.count().desc())

    sql = _annotate_sql(query, dialect)

    assert "ORDER BY (SELECT COUNT(*)" in sql, sql


def test_an_aggregate_over_a_child_column_is_re_anchored_in_the_order_by_too() -> None:
    """`sum_(Maker.id)` sorts by the sum, with the argument anchored to the subquery's alias.

    The argument is a column OF THE CHILD, so it belongs to the alias and not to the parent table. It
    is the same re-anchoring the projection does — which is the point: one rule, every clause.
    """
    query = SnakeQuery(Nation).order_by(Nation.makers.sum_(Maker.id).asc())

    sql = _annotate_sql(query, PostgresDialect())

    assert sql.endswith(
        'ORDER BY (SELECT SUM(e1."id") FROM "public"."makers" AS e1 '
        'WHERE e1."nation_id" = "nations"."id") ASC'
    ), sql


def test_ordering_by_a_plain_column_is_untouched() -> None:
    """The clause that already worked keeps working, with no subquery anywhere near it."""
    query = SnakeQuery(Nation).order_by(Nation.name.asc())

    sql = _annotate_sql(query, PostgresDialect())

    assert sql.endswith('ORDER BY "name" ASC'), sql


def test_a_plain_projection_sorts_by_it_too() -> None:
    """`select()` already PROJECTED a correlated aggregate, so it has to be able to sort by one.

    That asymmetry is what made the defect look like a rule and not a bug: the same statement, built
    the same way, accepted the subquery in one clause and refused it in the next. `annotate` is not a
    special case here — it is one of two entry points into the same emitter, and both are checked so
    a fix in one cannot pass while the other stays broken.
    """
    query = SnakeQuery(Nation).order_by(Nation.makers.count().desc())

    sql, _ = query.to_project_sql(PostgresDialect(), (Nation.name, count()))

    assert sql.endswith(
        'ORDER BY (SELECT COUNT(*) FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id") DESC'
    ), sql
