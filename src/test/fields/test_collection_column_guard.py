"""The aggregates and the `.any()` of a collection only accept columns OF THE CHILD.

`Nation.makers.sum_(Truck.id)` used to pass mypy and pyright: `SnakeExpr[T]` carries the type of the
VALUE, not the owning model, so `Maker.id` and `Truck.id` are twins as far as the checker can tell.
At runtime it emitted `SUM(e0."id")` over `makers` — valid SQL, the answer to a different question.
Silently.

The owner CANNOT live in the type. It was checked with a spike: if the CONDITION carried the owning
model, `filter(Truck.maker.nation.name == "España")` would stop compiling (the owner of that column
is `Nation`, not `Truck`) and neither would `(cond_of_Truck) & (cond_of_Nation)`. That is, killing
deep navigation, which is the thesis of this project. So the guard here is a runtime one, knowingly,
and it fails LOUD.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeUnknownColumn
from snakeorm.linker.linker import snake_link
from test.scenarios.deep_domain import Maker, Nation, Truck

snake_link()


def test_aggregate_accepts_a_column_of_the_child() -> None:
    """The correct case is left alone: `Maker.id` really is a column of `makers`."""
    assert Nation.makers.sum_(Maker.id) is not None


def test_aggregate_rejects_a_column_of_another_model() -> None:
    """`Truck.id` is no column of `makers`: it must fail instead of summing the child's ids."""
    with pytest.raises(SnakeUnknownColumn) as error:
        Nation.makers.sum_(Truck.model)
    assert "makers" in str(error.value)
    assert "model" in str(error.value)


def test_aggregate_rejects_a_navigated_column() -> None:
    """A column reached through navigation is no DIRECT column of the child: it is rejected."""
    with pytest.raises(
        SnakeUnknownColumn,
        match="A collection's aggregates only accept direct columns of the",
    ):
        Nation.makers.avg(Maker.nation.id)


def test_any_accepts_a_condition_over_the_child() -> None:
    """The correct case is left alone: `Maker.name` really is a column of `makers`."""
    assert Nation.makers.any(Maker.name == "SEAT") is not None


def test_any_rejects_a_condition_over_another_model() -> None:
    """`Truck.model` is no column of `makers`: the condition of the EXISTS is rejected."""
    with pytest.raises(
        SnakeUnknownColumn, match="of a collection filters by columns of the child or"
    ):
        Nation.makers.any(Truck.model == "Ibiza")


def test_any_accepts_a_navigated_condition() -> None:
    """Navigating a to-one relation of the child inside the EXISTS IS valid: `Maker.nation.name`.

    The first leg (`nation`) is a to-one relation of `makers` and the last one (`name`) a column of
    the target: the navigation happens inside the subquery. Nothing is raised.
    """
    assert Nation.makers.any(Maker.nation.name == "España") is not None


def test_any_rejects_a_navigated_path_with_an_unknown_first_step() -> None:
    """A first leg that is neither column nor relation of the child stays `SnakeUnknownColumn`.

    `Truck.maker.name` starts at `maker`, which is NOT a column nor a relation of `makers` (it
    belongs to `trucks`): there is nowhere to navigate, so it is rejected as an unknown column.
    """
    with pytest.raises(
        SnakeUnknownColumn,
        match="'maker' is neither a column nor a relation of 'makers':",
    ):
        Nation.makers.any(Truck.maker.name == "SEAT")


def test_nested_any_still_works() -> None:
    """A nested `.any()` still holds up: the child of the child is a collection, not a column."""
    assert Nation.makers.any(Maker.trucks.any(Truck.model == "Ibiza")) is not None


def test_count_without_argument_is_untouched() -> None:
    """`COUNT(*)` carries no column: there is nothing to validate."""
    assert Nation.makers.count() is not None
