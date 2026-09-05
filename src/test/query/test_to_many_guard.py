"""Tests of the JoinPlan runtime net: a flat path crossing a to-many blows up.

The real guard is the type system (`Nation.makers.name` does not compile). This one is the runtime
safety net: if a flat path `("makers", "name")` reaches the JOIN planner (say, hand-built or coming
through a proxy), the unrunnable inverted JOIN is not generated — SnakeUnsupportedFeature is raised
showing the alternative (`.any(...)` or `.join(...)`).
"""

from __future__ import annotations

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.linker import snake_link
from snakeorm.registry import registry
from snakeorm.sql import JoinPlan
from test.scenarios.deep_domain import Nation


def test_flat_path_through_to_many_raises() -> None:
    """Checks that a prefix crossing a to-many ('makers') raises SnakeUnsupportedFeature."""
    snake_link()
    table = registry.table_of(Nation)
    assert table is not None
    with pytest.raises(SnakeUnsupportedFeature, match="makers"):
        JoinPlan(table, [("makers", "name")], PostgresDialect(), registry)
