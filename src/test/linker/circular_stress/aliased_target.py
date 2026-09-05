"""The far side of the alias case. Points back, so neither module can import the other."""

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
    from test.linker.circular_stress.aliased import Aliaser


@snake_model(table="stress_aliased_targets", registry=stress_registry)
class Target(SnakeModel):
    """A NULLABLE to-one across the boundary: the optional unwrapping has to survive the fallback."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    owner_id: SnakeColumn[int | None] = snake_int()
    owner: SnakeToOne[Aliaser | None] = snake_to_one(owner_id)
