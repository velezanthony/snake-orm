"""The other half of the quoted pair, written the same way."""

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
    from test.linker.circular_stress.quoted_only import Quoter


@snake_model(table="stress_quoted_targets", registry=stress_registry)
class Quoted(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    owner_id: SnakeColumn[int] = snake_int()
    owner: SnakeToOne["Quoter"] = snake_to_one(owner_id)
