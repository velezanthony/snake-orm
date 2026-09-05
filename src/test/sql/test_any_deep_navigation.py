"""Emitting `.any()` when its condition NAVIGATES to-one relations of the child inside the EXISTS.

`Nation.makers.any(Maker.nation.name == "España")` no longer filters by a DIRECT column of the child:
it navigates `Maker.nation` INSIDE the correlated subquery. That forces emitting the JOINs of that
navigation with an alias space OF ITS OWN, one that does not collide with:
  - the `e0, e1...` of the EXISTS itself (the child base + nested subqueries),
  - the `t0, t1...` of the outer query,
  - the correlated `parent_ref`.

What is checked: one hop, two hops, combining with a direct column via `&`, non-collision with the
outer query's JOINs, and a COMPOSITE FK in the navigated JOIN (both pairs AND-ed).
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Maker, Nation, Truck
from test.scenarios.test_composite_keys import Province


def test_one_hop_navigation_emits_a_join_inside_the_exists() -> None:
    """One hop (`Maker.nation.name`) adds `JOIN nations AS e1` inside the EXISTS and qualifies by e1."""
    snake_link()
    sql, params = (
        SnakeQuery(Nation)
        .filter(Nation.makers.any(Maker.nation.name == "España"))
        .to_sql(PostgresDialect())
    )
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE EXISTS (SELECT 1 FROM "public"."makers" AS e0 '
        'JOIN "public"."nations" AS e1 ON e0."nation_id" = e1."id" '
        'WHERE e0."nation_id" = "nations"."id" AND e1."name" = %s)'
    )
    assert params == ("España",)


def test_two_hop_navigation_chains_two_joins_inside_the_exists() -> None:
    """Two hops (`Truck.maker.nation.name`) chain `JOIN makers e1` and `JOIN nations e2`."""
    snake_link()
    sql, params = (
        SnakeQuery(Maker)
        .filter(Maker.trucks.any(Truck.maker.nation.name == "España"))
        .to_sql(PostgresDialect())
    )
    assert sql == (
        'SELECT "id", "name", "nation_id" FROM "public"."makers" '
        'WHERE EXISTS (SELECT 1 FROM "public"."trucks" AS e0 '
        'JOIN "public"."makers" AS e1 ON e0."maker_id" = e1."id" '
        'JOIN "public"."nations" AS e2 ON e1."nation_id" = e2."id" '
        'WHERE e0."maker_id" = "makers"."id" AND e2."name" = %s)'
    )
    assert params == ("España",)


def test_direct_and_navigated_columns_combine_with_and() -> None:
    """A direct column (`Maker.name`) and a navigated one (`Maker.nation.name`) live together under `&`: only 1 JOIN."""
    snake_link()
    sql, params = (
        SnakeQuery(Nation)
        .filter(
            Nation.makers.any((Maker.name == "SEAT") & (Maker.nation.name == "España"))
        )
        .to_sql(PostgresDialect())
    )
    assert sql == (
        'SELECT "id", "name" FROM "public"."nations" '
        'WHERE EXISTS (SELECT 1 FROM "public"."makers" AS e0 '
        'JOIN "public"."nations" AS e1 ON e0."nation_id" = e1."id" '
        'WHERE e0."nation_id" = "nations"."id" '
        'AND (e0."name" = %s AND e1."name" = %s))'
    )
    assert params == ("SEAT", "España")


def test_navigated_exists_does_not_collide_with_outer_query_joins() -> None:
    """With JOINs in the outer query (t0, t1) and navigation inside the EXISTS (e0, e1, e2), they do not clash.

    The correlated `parent_ref` is the outer root alias (t0), and the subquery aliases (base +
    navigated JOINs + nested ones) come out of a monotonic counter OF ITS OWN (e0, e1, e2...).
    """
    snake_link()
    sql, params = (
        SnakeQuery(Maker)
        .filter(Maker.nation.name == "España")
        .filter(Maker.trucks.any(Truck.maker.nation.name == "España"))
        .to_sql(PostgresDialect())
    )
    assert sql == (
        'SELECT t0."id", t0."name", t0."nation_id" '
        'FROM "public"."makers" AS t0 '
        'JOIN "public"."nations" AS t1 ON t0."nation_id" = t1."id" '
        'WHERE (t1."name" = %s AND EXISTS (SELECT 1 FROM "public"."trucks" AS e0 '
        'JOIN "public"."makers" AS e1 ON e0."maker_id" = e1."id" '
        'JOIN "public"."nations" AS e2 ON e1."nation_id" = e2."id" '
        'WHERE e0."maker_id" = t0."id" AND e2."name" = %s))'
    )
    assert params == ("España", "España")


def test_navigated_composite_fk_ands_both_pairs_in_the_join() -> None:
    """Navigating a relation with a COMPOSITE FK (`Town.province`) ANDs both pairs in the inner JOIN."""
    snake_link()
    from test.scenarios.test_composite_keys import Town

    sql, params = (
        SnakeQuery(Province)
        .filter(Province.towns.any(Town.province.name == "Northland"))
        .to_sql(PostgresDialect())
    )
    assert sql == (
        'SELECT "region", "code", "name" FROM "public"."kv_provinces" '
        'WHERE EXISTS (SELECT 1 FROM "public"."kv_towns" AS e0 '
        'JOIN "public"."kv_provinces" AS e1 '
        'ON e0."province_region" = e1."region" AND e0."province_code" = e1."code" '
        'WHERE e0."province_region" = "kv_provinces"."region" '
        'AND e0."province_code" = "kv_provinces"."code" '
        'AND e1."name" = %s)'
    )
    assert params == ("Northland",)
