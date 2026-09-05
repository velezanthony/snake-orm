"""Tests of the correlated EXISTS emitted by `collection.any(...)`.

The right SQL for a to-many is NOT a flat JOIN (that was the bug: inverted ON, an FK column that
does not exist on the parent). It is a correlated EXISTS: the FK lives on the CHILD, so the ON goes
`<child>.<fk> = <parent>.<pk>`. Covered here: with no condition, with a condition, negated and
NESTED (an `.any()` inside another), checking that the subquery aliases (e0, e1...) do not collide
with the outer query's and that the params come out in order and parameterised.
"""

from __future__ import annotations

from snakeorm import snake_case
from snakeorm.dialects import PostgresDialect
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Maker, Nation, Truck


def test_any_without_condition_emits_correlated_exists() -> None:
    """Checks the EXISTS of `.any()` with no condition: just the child→parent correlation."""
    snake_link()
    sql, params = (
        SnakeQuery(Nation).filter(Nation.makers.any()).to_sql(PostgresDialect())
    )
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE EXISTS (SELECT 1 FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id")'
    )
    assert params == ()


def test_any_with_condition_reanchors_child_paths_to_the_subquery_alias() -> None:
    """Checks that the child's condition (`Maker.name`) is re-anchored to alias e0 and parameterised."""
    snake_link()
    sql, params = (
        SnakeQuery(Nation)
        .filter(Nation.makers.any(Maker.name == "SEAT"))
        .to_sql(PostgresDialect())
    )
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE EXISTS (SELECT 1 FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id" AND e0."name" = %s)'
    )
    assert params == ("SEAT",)


def test_negated_any_wraps_the_exists_in_not() -> None:
    """Checks that `~collection.any()` emits `NOT (EXISTS (...))`."""
    snake_link()
    sql, params = (
        SnakeQuery(Nation).filter(~Nation.makers.any()).to_sql(PostgresDialect())
    )
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE NOT (EXISTS (SELECT 1 FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id"))'
    )
    assert params == ()


def test_nested_any_uses_distinct_aliases_and_ordered_params() -> None:
    """Checks nesting: `.any()` inside `.any()` yields distinct aliases (e0, e1) that nest properly."""
    snake_link()
    sql, params = (
        SnakeQuery(Nation)
        .filter(Nation.makers.any(Maker.trucks.any(Truck.model == "Ibiza")))
        .to_sql(PostgresDialect())
    )
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE EXISTS (SELECT 1 FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id" AND '
        'EXISTS (SELECT 1 FROM "public"."trucks" AS e1 '
        'WHERE e1."maker_id" = e0."id" AND e1."model" = %s))'
    )
    assert params == ("Ibiza",)


def test_ordering_by_a_case_over_exists_keeps_the_correlation() -> None:
    """Checks that a correlated EXISTS survives into the ORDER BY, not only into the WHERE."""
    snake_link()
    ranking = snake_case((Nation.makers.any(), 1), default=0)

    sql, params = SnakeQuery(Nation).order_by(ranking.desc()).to_sql(PostgresDialect())

    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'ORDER BY CASE WHEN EXISTS (SELECT 1 FROM "public"."makers" AS e0 '
        'WHERE e0."nation_id" = "nations"."id") THEN %s ELSE %s END DESC'
    )
    assert params == (1, 0)


def test_the_includes_emitter_correlates_its_order_by_too() -> None:
    """The same guarantee on `emit_select_with_includes`, which carried the identical defect."""
    snake_link()
    ranking = snake_case((Maker.trucks.any(), 1), default=0)

    sql, params = (
        SnakeQuery(Maker)
        .include(Maker.nation)
        .order_by(ranking.desc())
        .to_include_sql(PostgresDialect())
    )

    assert sql.endswith(
        'ORDER BY CASE WHEN EXISTS (SELECT 1 FROM "public"."trucks" AS e0 '
        'WHERE e0."maker_id" = t0."id") THEN %s ELSE %s END DESC'
    )
    assert params == (1, 0)
