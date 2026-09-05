"""Tests of SnakeQuery with deep navigation: filters through relations generate JOINs.

`SnakeQuery(Truck).filter(Truck.maker.nation.name == "España")` compiles a SELECT with the JOINs
and the qualified columns. Without deep navigation the SQL stays alias-free (backwards compat).
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Truck


def test_shallow_filter_stays_unqualified() -> None:
    """Checks that a filter on an own column generates NO alias and NO JOINs (backwards compat)."""
    snake_link()
    sql, _ = SnakeQuery(Truck).filter(Truck.model == "Ibiza").to_sql(PostgresDialect())
    assert " AS t0" not in sql
    assert "JOIN" not in sql
    assert sql.endswith('WHERE "model" = %s')


def test_deep_filter_generates_joins_and_qualifies() -> None:
    """Checks that a deep filter generates the JOINs and qualifies the columns."""
    snake_link()
    query = SnakeQuery(Truck).filter(Truck.maker.nation.name == "España")
    sql, params = query.to_sql(PostgresDialect())
    assert sql == (
        'SELECT t0."id", t0."model", t0."maker_id" FROM "public"."trucks" AS t0 '
        'JOIN "public"."makers" AS t1 ON t0."maker_id" = t1."id" '
        'JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id" '
        'WHERE t2."name" = %s'
    )
    assert params == ("España",)


def test_deep_filter_mixes_root_and_relation_columns() -> None:
    """Checks that mixing an own column with a deep column qualifies both correctly."""
    snake_link()
    query = SnakeQuery(Truck).filter(Truck.model == "Ibiza", Truck.maker.name == "SEAT")
    sql, params = query.to_sql(PostgresDialect())
    assert '(t0."model" = %s AND t1."name" = %s)' in sql
    assert 'JOIN "public"."makers" AS t1' in sql
    assert params == ("Ibiza", "SEAT")
