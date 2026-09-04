"""Tests of the `collection.count()` scalar subquery.

`.count()` does not change the cardinality of the outer query: it is a correlated scalar VALUE
`(SELECT COUNT(*) FROM child AS alias WHERE correlation)`, comparable like any other value. That is
why `Nation.makers.count() > 3` is a valid condition in a WHERE, with no JOIN and no duplicates.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Nation


def test_count_emits_correlated_scalar_subquery_in_where() -> None:
    """Checks that `.count() > 3` emits the correlated COUNT(*) as a scalar value in the WHERE."""
    snake_link()
    sql, params = (
        SnakeQuery(Nation).filter(Nation.makers.count() > 3).to_sql(PostgresDialect())
    )
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE (SELECT COUNT(*) FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id") > %s'
    )
    assert params == (3,)


def test_count_contributes_no_outer_paths() -> None:
    """Checks that the count node contributes no paths to the outer query (correlation is internal)."""
    snake_link()
    assert Nation.makers.count().paths() == ()
