"""CLASS access to a to-many: it returns a SnakeCollection, not a navigable proxy.

The design decision: implicit when the answer is unique (to-one → deep navigation), explicit when
there is more than one correct answer (to-many → collection operations). That is why `Nation.makers`
stops exposing the child's columns and offers only `.any()` and `.count()`. The inverted JOIN thus
stops being writable at all: `Nation.makers.name` is an error, not SQL that cannot be executed.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeRelationshipNotLoaded
from snakeorm.expressions import SnakeExists, SnakeNot, SnakeSubqueryAggregate
from snakeorm.fields.relationship import SnakeCollection
from snakeorm.fields.relationship import attach_relationship
from snakeorm.linker import snake_link
from test.scenarios.deep_domain import Maker, Nation


def test_class_access_returns_a_collection() -> None:
    """CLASS access to a to-many returns a SnakeCollection."""
    snake_link()
    assert isinstance(Nation.makers, SnakeCollection)


def test_any_returns_a_snake_exists() -> None:
    """`.any()` with no condition produces a SnakeExists node of the boolean AST."""
    snake_link()
    node = Nation.makers.any()
    assert isinstance(node, SnakeExists)
    assert node.condition is None


def test_any_with_condition_carries_the_child_condition() -> None:
    """`.any(cond)` keeps the child's condition so it can be emitted inside the EXISTS."""
    snake_link()
    node = Nation.makers.any(Maker.name == "SEAT")
    assert isinstance(node, SnakeExists)
    assert node.condition is not None


def test_negated_any_is_a_snake_not() -> None:
    """`~collection.any()` yields a SnakeNot: EXISTS inherits from SnakeCondition."""
    snake_link()
    assert isinstance(~Nation.makers.any(), SnakeNot)


def test_count_returns_a_subquery_aggregate() -> None:
    """`.count()` produces a SnakeSubqueryAggregate: a comparable scalar value."""
    snake_link()
    assert isinstance(Nation.makers.count(), SnakeSubqueryAggregate)


def test_scalar_aggregates_return_a_subquery_aggregate() -> None:
    """sum_/avg/min_/max_ also produce a SnakeSubqueryAggregate over the child's column."""
    snake_link()
    assert isinstance(Nation.makers.sum_(Maker.id), SnakeSubqueryAggregate)
    assert isinstance(Nation.makers.avg(Maker.id), SnakeSubqueryAggregate)
    assert isinstance(Nation.makers.min_(Maker.id), SnakeSubqueryAggregate)
    assert isinstance(Nation.makers.max_(Maker.id), SnakeSubqueryAggregate)


def test_collection_does_not_expose_child_columns() -> None:
    """The SnakeCollection does NOT navigate the child's columns: the bug is no longer writable."""
    snake_link()
    with pytest.raises(AttributeError):
        _ = Nation.makers.name  # type: ignore[attr-defined]


def test_instance_access_still_raises_when_not_loaded() -> None:
    """INSTANCE access does not change: unloaded, it still blows up. That is the N+1 padlock."""
    snake_link()
    nation = Nation(id=1, name="España")
    with pytest.raises(SnakeRelationshipNotLoaded, match="Relation 'makers' was not"):
        _ = nation.makers


def test_instance_access_returns_the_loaded_list() -> None:
    """INSTANCE access returns the loaded list exactly as it is.

    It is hung with `attach_relationship` (the loader's door) because assigning a relation is FORBIDDEN
    ever since `__set__` raises: reading one and writing one are no longer the same operation.
    """
    snake_link()
    nation = Nation(id=1, name="España")
    makers = [Maker(id=1, name="SEAT", nation_id=1)]
    attach_relationship(nation, "makers", makers)
    assert nation.makers == makers
