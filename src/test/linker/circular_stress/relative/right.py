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
from test.linker.circular_stress import stress_registry

if TYPE_CHECKING:
    from .left import Left


@snake_model(table="stress_rel_right", registry=stress_registry)
class Right(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    left_id: SnakeColumn[int] = snake_int()
    left: SnakeToOne[Left] = snake_to_one(left_id)
