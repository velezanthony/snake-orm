"""crm's items. Points back at crm's Order."""

from __future__ import annotations

from typing import TYPE_CHECKING

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToOne,
    snake_int,
    snake_model,
    snake_to_one,
)
from test.linker.circular_stress import crm_registry

if TYPE_CHECKING:
    from test.linker.circular_stress.homonyms.crm.orders import Order


@snake_model(table="stress_crm_items", registry=crm_registry)
class Item(SnakeModel):
    """Homonymous with the other app's Item, on purpose."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    order_id: SnakeColumn[int] = snake_int()
    order: SnakeToOne[Order] = snake_to_one(order_id)
