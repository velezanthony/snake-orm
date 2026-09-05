"""Tests of emit_select with a JoinPlan: SELECT with aliases, JOINs and qualified columns.

No plan → single-table with no alias (covered in test_select). With a plan → the root is t0, the
JOINs are added and every column gets qualified. The result is always the root table.
"""

from __future__ import annotations

from snakeorm.decorators import snake_table
from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.linker import snake_link
from snakeorm.registry import registry
from snakeorm.sql import JoinPlan, emit_select
from test.scenarios.deep_domain import Truck


def _plan(*paths: tuple[str, ...]) -> JoinPlan:
    """JoinPlan over Truck for the given paths (after linking)."""
    snake_link()
    return JoinPlan(snake_table(Truck), paths, PostgresDialect(), registry)


def test_select_with_plan_aliases_root_columns() -> None:
    """Checks that with a plan the root columns are qualified with t0 and the table carries AS t0."""
    plan = _plan(("maker", "name"))
    sql, _ = emit_select(snake_table(Truck), PostgresDialect(), plan=plan)
    assert sql.startswith(
        'SELECT t0."id", t0."model", t0."maker_id" FROM "public"."trucks" AS t0'
    )


def test_select_with_plan_emits_joins() -> None:
    """Checks that the SELECT includes the plan's JOIN clauses."""
    plan = _plan(("maker", "nation", "name"))
    sql, _ = emit_select(snake_table(Truck), PostgresDialect(), plan=plan)
    assert 'JOIN "public"."makers" AS t1 ON t0."maker_id" = t1."id"' in sql
    assert 'JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id"' in sql


def test_select_with_plan_qualifies_where() -> None:
    """Checks that the WHERE qualifies the deep column with the right alias (t2)."""
    where = SnakeExpr[str](path=("maker", "nation", "name")) == "España"
    plan = _plan(("maker", "nation", "name"))
    sql, params = emit_select(
        snake_table(Truck), PostgresDialect(), where=where, plan=plan
    )
    assert sql.endswith('WHERE t2."name" = %s')
    assert params == ("España",)
