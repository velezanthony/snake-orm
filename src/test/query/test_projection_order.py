"""Projection (`.select()`) must honour ORDER BY, LIMIT and OFFSET.

Until now `to_project_sql` IGNORED THEM SILENTLY: it collected the `order_by` paths to plan the
JOINs, but it never emitted the clause. You asked for `.order_by(...).limit(5)` and got every row
back, unordered, without a single warning. An `.all()` did honour them.
"""

from __future__ import annotations

from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.expressions import count
from snakeorm.linker.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Truck

snake_link()
DIALECT = PostgresDialect()


def test_projection_emits_order_by() -> None:
    """An `order_by` on the query shows up in the projection's SQL."""
    sql, params = (
        SnakeQuery(Truck)
        .order_by(Truck.model.asc())
        .to_project_sql(DIALECT, [Truck.model])
    )
    assert sql == 'SELECT "model" FROM "public"."trucks" ORDER BY "model" ASC'
    assert params == ()


def test_projection_emits_limit_and_offset() -> None:
    """`limit`/`offset` are emitted parameterised, just like in a normal SELECT."""
    sql, params = (
        SnakeQuery(Truck).limit(5).offset(10).to_project_sql(DIALECT, [Truck.model])
    )
    assert sql == 'SELECT "model" FROM "public"."trucks" LIMIT %s OFFSET %s'
    assert params == (5, 10)


def test_projection_orders_by_a_deep_path() -> None:
    """Ordering by a deep relation qualifies the column with the JOIN's alias."""
    sql, _ = (
        SnakeQuery(Truck)
        .order_by(Truck.maker.nation.name.desc())
        .to_project_sql(DIALECT, [Truck.model])
    )
    assert 'ORDER BY t2."name" DESC' in sql
    assert "JOIN" in sql


def test_clause_order_is_group_by_having_order_by_limit() -> None:
    """The clauses come out in the order SQL demands: GROUP BY, HAVING, ORDER BY, LIMIT."""
    sql, params = (
        SnakeQuery(Truck)
        .group_by(Truck.model)
        .having(count() > 1)
        .order_by(Truck.model.asc())
        .limit(3)
        .to_project_sql(DIALECT, [Truck.model, count()])
    )
    assert sql == (
        'SELECT "model", COUNT(*) FROM "public"."trucks" '
        'GROUP BY "model" HAVING COUNT(*) > %s ORDER BY "model" ASC LIMIT %s'
    )
    assert params == (1, 3)
