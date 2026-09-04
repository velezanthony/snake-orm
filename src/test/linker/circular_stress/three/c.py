"""Link c of the three-module cycle: needs a, which needs the next one, which needs c."""

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
from test.linker.circular_stress import three_registry

if TYPE_CHECKING:
    from test.linker.circular_stress.three.a import NodeA


@snake_model(table="stress_three_c", registry=three_registry)
class NodeC(SnakeModel):
    """Points at the next link. No module of the three imports another at runtime."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    next_id: SnakeColumn[int] = snake_int()
    nxt: SnakeToOne[NodeA] = snake_to_one(next_id)
