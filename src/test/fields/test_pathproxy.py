"""The PathProxy: runtime navigation over the graph once it is ALREADY linked.

`Car.brand.name` → a SnakeExpr carrying the accumulated path; the query compiler derives the JOINs.
"""

from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.expressions import SnakeExpr
from snakeorm.fields import SnakeColumn, SnakeToOne, snake_int, snake_str, snake_to_one

from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel


@snake_model(prefix="px")
class Brand(SnakeModel):
    """A brand."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(prefix="px")
class Car(SnakeModel):
    """A car with an FK to Brand."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    brand_id: SnakeColumn[int] = snake_int()
    brand: SnakeToOne[Brand] = snake_to_one(brand_id)


@snake_model(prefix="px")
class Driver(SnakeModel):
    """A driver with an FK to Car (so deep navigation has somewhere to go)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    car_id: SnakeColumn[int] = snake_int()
    car: SnakeToOne[Car] = snake_to_one(car_id)


def test_navigate_to_target_column() -> None:
    """Navigating to a column of the target yields a SnakeExpr carrying the path."""
    snake_link()
    expr = Car.brand.name
    assert isinstance(expr, SnakeExpr)
    assert expr.path == ("brand", "name")


def test_deep_navigation_through_relations() -> None:
    """Deep navigation Driver.car.brand.name arrives with the whole path."""
    snake_link()
    expr = Driver.car.brand.name
    assert isinstance(expr, SnakeExpr)
    assert expr.path == ("car", "brand", "name")
