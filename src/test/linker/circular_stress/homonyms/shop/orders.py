"""shop's orders. Points at ITS OWN Item, which shares a class name with the other app's."""

from __future__ import annotations

from typing import TYPE_CHECKING

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToMany,
    snake_int,
    snake_model,
    snake_to_many,
)
from test.linker.circular_stress import shop_registry

if TYPE_CHECKING:
    from test.linker.circular_stress.homonyms.shop.items import Item


@snake_model(table="stress_shop_orders", registry=shop_registry)
class Order(SnakeModel):
    """Its `items` must land on shop's Item and never on the other app's."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    items: SnakeToMany[Item] = snake_to_many("order")
