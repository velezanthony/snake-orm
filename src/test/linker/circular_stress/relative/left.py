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
from test.linker.circular_stress import stress_registry

if TYPE_CHECKING:
    from .right import Right  # RELATIVO


@snake_model(table="stress_rel_left", registry=stress_registry)
class Left(SnakeModel):
    """Its target is named through a relative import."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    rights: SnakeToMany[Right] = snake_to_many("left")
