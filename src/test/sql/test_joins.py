"""Tests of the JOIN planner: relation paths → table aliases + JOIN clauses.

Every path is ("rel1", "rel2", ..., "column"). The planner resolves the linked graph, assigns
aliases (t0 for the root, t1, t2...) and generates one JOIN per UNIQUE relation prefix (dedup).

The models (Truck→Maker→Nation) live in test.scenarios.deep_domain (shared).
"""

from __future__ import annotations

import pytest

from snakeorm.decorators import snake_table
from snakeorm.dialects import PostgresDialect
from snakeorm.linker import snake_link
from snakeorm.registry import registry
from snakeorm.sql import JoinPlan
from test.scenarios.deep_domain import Truck


def _plan(*paths: tuple[str, ...]) -> JoinPlan:
    """Builds a JoinPlan over Truck for the given paths (after linking)."""
    snake_link()
    return JoinPlan(snake_table(Truck), paths, PostgresDialect(), registry)


def test_no_relationships_means_no_joins() -> None:
    """Checks that a column-only path (no relations) generates no JOINs; root = t0."""
    plan = _plan(("id",))
    assert plan.has_joins is False
    assert plan.alias_for(()) == "t0"


def test_single_relationship_join() -> None:
    """Checks a one-level JOIN with its alias and the ON over the FK pairs."""
    plan = _plan(("maker", "name"))
    assert plan.alias_for(("maker",)) == "t1"
    assert plan.joins == ('JOIN "public"."makers" AS t1 ON t0."maker_id" = t1."id"',)


def test_deep_relationship_joins() -> None:
    """Checks a two-level chain: Truck→Maker (t1) →Nation (t2), in order."""
    plan = _plan(("maker", "nation", "name"))
    assert plan.alias_for(("maker",)) == "t1"
    assert plan.alias_for(("maker", "nation")) == "t2"
    assert plan.joins == (
        'JOIN "public"."makers" AS t1 ON t0."maker_id" = t1."id"',
        'JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id"',
    )


def test_shared_prefix_is_joined_once() -> None:
    """Checks dedup: two paths sharing `maker` produce ONE single makers JOIN."""
    plan = _plan(("maker", "name"), ("maker", "nation", "name"))
    assert sum("makers" in join for join in plan.joins) == 1
    assert len(plan.joins) == 2  # makers (t1) + nations (t2)


def test_unknown_relationship_raises() -> None:
    """Checks that a hop which is not a relation of the model fails clearly."""
    with pytest.raises(
        ValueError, match="does not have a relationship named 'inexistente'"
    ):
        _plan(("inexistente", "x"))
