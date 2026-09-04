"""Tests of the scalar aggregate subquery `collection.sum_/avg/min_/max_` (and `count`).

It generalises `.count()`: each function emits `(SELECT FUNC(arg) FROM child AS alias WHERE
correlation)`, with the argument (a column OF THE CHILD) re-anchored to the subquery alias, EXACTLY
like `.any()`'s condition. They are comparable scalar values, so they live in a WHERE (`> 3`, `== 0`).
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeCondition
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Maker, Nation


def _where(node: SnakeCondition) -> tuple[str, tuple[object, ...]]:
    """Compiles `SELECT ... FROM nations WHERE <node>` and returns `(sql, params)`."""
    snake_link()
    return SnakeQuery(Nation).filter(node).to_sql(PostgresDialect())


def test_sum_emits_correlated_scalar_subquery_with_reanchored_arg() -> None:
    """`.sum_(col)` emits a correlated `SUM(<col re-anchored to the alias>)`, comparable in the WHERE."""
    sql, params = _where(Nation.makers.sum_(Maker.id) > 5)
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE (SELECT SUM(e0."id") FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id") > %s'
    )
    assert params == (5,)


def test_avg_emits_correlated_scalar_subquery_with_reanchored_arg() -> None:
    """`.avg(col)` emits a correlated `AVG(<re-anchored col>)`, comparable against a float."""
    sql, params = _where(Nation.makers.avg(Maker.id) > 100.0)
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE (SELECT AVG(e0."id") FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id") > %s'
    )
    assert params == (100.0,)


def test_min_emits_correlated_scalar_subquery_with_reanchored_arg() -> None:
    """`.min_(col)` emits a correlated `MIN(<re-anchored col>)`."""
    sql, params = _where(Nation.makers.min_(Maker.id) == 0)
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE (SELECT MIN(e0."id") FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id") = %s'
    )
    assert params == (0,)


def test_max_emits_correlated_scalar_subquery_with_reanchored_arg() -> None:
    """`.max_(col)` emits a correlated `MAX(<re-anchored col>)`."""
    sql, params = _where(Nation.makers.max_(Maker.id) > 3)
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE (SELECT MAX(e0."id") FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id") > %s'
    )
    assert params == (3,)


def test_count_still_emits_the_same_star_subquery() -> None:
    """`.count()` still emits the correlated `COUNT(*)` (no argument), bit for bit as before."""
    sql, params = _where(Nation.makers.count() == 0)
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE (SELECT COUNT(*) FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id") = %s'
    )
    assert params == (0,)


def test_collection_aggregates_contribute_no_outer_paths() -> None:
    """A correlated aggregate contributes no paths to the outer query (correlation is internal)."""
    snake_link()
    assert Nation.makers.sum_(Maker.id).paths() == ()
    assert Nation.makers.avg(Maker.id).paths() == ()
    assert Nation.makers.max_(Maker.id).paths() == ()
