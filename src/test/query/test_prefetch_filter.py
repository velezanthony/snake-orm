"""Tests for `SnakePrefetch.filter()`: it narrows WHICH CHILDREN load at a level, never dropping parents.

Unlike `query.filter()` (which discards parents), a prefetch filter attaches to the LAST hop declared
(the current level) and narrows its select-in. What is tested here is the OBJECT: that the condition
lands on the right hop, that it accumulates with AND, that chaining `.filter().then().filter()` puts
each condition at its own level, and that a navigated column or one from another model is rejected.
SQL EMISSION and EXECUTION are tested in test/session/.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeUnknownColumn
from snakeorm.expressions import SnakeAnd
from snakeorm.fields import SnakePrefetch
from snakeorm.linker import snake_link
from test.scenarios.deep_domain import Maker, Nation, Truck


def test_filter_attaches_the_condition_to_the_root_hop() -> None:
    """With no `.then()`, `.filter()` goes to the FIRST level (the makers): the root hop carries the condition."""
    snake_link()
    condition = Maker.name == "SEAT"
    prefetch = SnakePrefetch(Nation.makers).filter(condition)
    hops = prefetch.hops()
    assert hops[0].child_filter is condition


def test_filter_accumulates_conditions_with_and() -> None:
    """Two `.filter()` calls at the same level combine with AND (just like `query.filter`)."""
    snake_link()
    first = Maker.name == "SEAT"
    second = Maker.id > 1
    prefetch = SnakePrefetch(Nation.makers).filter(first).filter(second)
    child_filter = prefetch.hops()[0].child_filter
    assert isinstance(child_filter, SnakeAnd)
    assert child_filter.parts == (first, second)


def test_filter_is_immutable_and_returns_a_new_prefetch() -> None:
    """`.filter()` does not mutate the original prefetch: it returns a new one with the hop updated."""
    snake_link()
    base = SnakePrefetch(Nation.makers)
    filtered = base.filter(Maker.name == "SEAT")
    assert base.hops()[0].child_filter is None  # the original did not change
    assert filtered.hops()[0].child_filter is not None
    assert filtered is not base


def test_filter_after_then_targets_the_new_level() -> None:
    """After a `.then(Maker.trucks)`, the next `.filter()` is for the TRUCKS, not for the makers."""
    snake_link()
    truck_condition = Truck.id > 2
    prefetch = SnakePrefetch(Nation.makers).then(Maker.trucks).filter(truck_condition)
    hops = prefetch.hops()
    assert hops[0].child_filter is None  # the makers level still has no filter
    assert (
        hops[1].child_filter is truck_condition
    )  # the filter lands on the trucks level


def test_filter_per_level_in_a_chain() -> None:
    """Chaining `.filter().then().filter()` puts EACH condition at its corresponding level."""
    snake_link()
    maker_condition = Maker.name == "SEAT"
    truck_condition = Truck.id > 2
    prefetch = (
        SnakePrefetch(Nation.makers)
        .filter(maker_condition)
        .then(Maker.trucks)
        .filter(truck_condition)
    )
    hops = prefetch.hops()
    assert hops[0].child_filter is maker_condition
    assert hops[1].child_filter is truck_condition


def test_filter_rejects_a_column_of_another_model() -> None:
    """A column that does not exist on the level's model (another model) → SnakeUnknownColumn."""
    snake_link()
    with pytest.raises(
        SnakeUnknownColumn, match="only narrows by columns of that level's"
    ):
        # `Truck.model` is not a column of `makers` (the current level): it is rejected.
        SnakePrefetch(Nation.makers).filter(Truck.model == "Ibiza")


def test_filter_rejects_a_navigated_column() -> None:
    """A NAVIGATED condition (a path of more than one hop) is not a direct column → SnakeUnknownColumn."""
    snake_link()
    with pytest.raises(
        SnakeUnknownColumn, match="only narrows by columns of that level's"
    ):
        # `Maker.nation.name` navigates a relation: it is not a direct column of the child.
        SnakePrefetch(Nation.makers).filter(Maker.nation.name == "España")
