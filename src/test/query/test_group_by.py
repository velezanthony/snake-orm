"""`group_by`/`having` on the projection: SQL, the ungrouped-column guard, and the relation JOIN.

`group_by` and `having` ride along in the projection (`to_project_sql`), which is where columns and
aggregates can be mixed. The SQL order is `... [WHERE] [GROUP BY] [HAVING]`. The paths of both feed
into the `JoinPlan`, so grouping by a deep relation generates its JOIN. At emission the guard catches
a projected column that is neither aggregated nor in the GROUP BY (Postgres would reject it anyway).
"""

from __future__ import annotations

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.expressions.functions import avg, count
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from test.scenarios.deep_domain import Truck


def test_group_by_emits_group_by_clause() -> None:
    """`group_by(col)` together with an aggregate emits `... GROUP BY <col>` after the FROM."""
    query = SnakeQuery(Truck).group_by(Truck.maker_id)
    sql, _ = query.to_project_sql(PostgresDialect(), [Truck.maker_id, count()])
    assert sql == (
        'SELECT "maker_id", COUNT(*) FROM "public"."trucks" GROUP BY "maker_id"'
    )


def test_having_after_group_by() -> None:
    """`having(count() > 1)` emits the HAVING after the GROUP BY, with the literal parameterised."""
    query = SnakeQuery(Truck).group_by(Truck.maker_id).having(count() > 1)
    sql, params = query.to_project_sql(PostgresDialect(), [Truck.maker_id, count()])
    assert sql.endswith('GROUP BY "maker_id" HAVING COUNT(*) > %s')
    assert params == (1,)


def test_having_accumulates_with_and() -> None:
    """Several `having` calls combine with AND (just like `filter`)."""
    query = (
        SnakeQuery(Truck)
        .group_by(Truck.maker_id)
        .having(count() > 1)
        .having(avg(Truck.id) > 0)
    )
    sql, params = query.to_project_sql(PostgresDialect(), [Truck.maker_id])
    assert 'HAVING (COUNT(*) > %s AND AVG("id") > %s)' in sql
    assert params == (1, 0)


def test_having_without_group_by_is_allowed() -> None:
    """`having` with no `group_by` is valid (a global aggregate): it emits HAVING with no GROUP BY."""
    query = SnakeQuery(Truck).having(count() > 5)
    sql, params = query.to_project_sql(PostgresDialect(), [count()])
    assert sql == 'SELECT COUNT(*) FROM "public"."trucks" HAVING COUNT(*) > %s'
    assert params == (5,)


def test_ungrouped_column_raises() -> None:
    """A projected column that is not aggregated and missing from the GROUP BY raises `SnakeEmitError`."""
    query = SnakeQuery(Truck).group_by(Truck.maker_id)
    with pytest.raises(SnakeEmitError, match="model"):
        query.to_project_sql(PostgresDialect(), [Truck.model, count()])


def test_grouped_column_passes_the_guard() -> None:
    """If EVERY non-aggregated column is in the GROUP BY, the guard lets it through."""
    query = SnakeQuery(Truck).group_by(Truck.maker_id, Truck.model)
    sql, _ = query.to_project_sql(
        PostgresDialect(), [Truck.maker_id, Truck.model, count()]
    )
    assert 'GROUP BY "maker_id", "model"' in sql


def test_group_by_on_deep_relation_generates_join() -> None:
    """`group_by(Truck.maker.name)` navigates a relation and generates its aliased JOIN."""
    snake_link()
    query = SnakeQuery(Truck).group_by(Truck.maker.name)
    sql, _ = query.to_project_sql(PostgresDialect(), [Truck.maker.name, count()])
    assert "JOIN" in sql
    assert 'GROUP BY t1."name"' in sql
    assert sql.startswith('SELECT t1."name", COUNT(*) FROM "public"."trucks" AS t0')


def test_having_on_deep_relation_generates_join() -> None:
    """`having` with an aggregate over a deep relation generates that relation's JOIN."""
    snake_link()
    query = (
        SnakeQuery(Truck)
        .group_by(Truck.maker_id)
        .having(count(Truck.maker.nation_id) > 1)
    )
    sql, _ = query.to_project_sql(PostgresDialect(), [Truck.maker_id, count()])
    assert "JOIN" in sql
    assert 'HAVING COUNT(t1."nation_id") > %s' in sql
