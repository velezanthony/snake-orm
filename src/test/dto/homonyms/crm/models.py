"""The `crm` application's own `Customer`."""

from __future__ import annotations

from snakeorm import SnakeColumn, snake_auto, snake_model, snake_str


@snake_model(table="dto_crm_customers")
class Customer:
    """A customer as `crm` understands one. Its columns are what says which is which."""

    id: SnakeColumn[int] = snake_auto()
    account: SnakeColumn[str] = snake_str(max_length=40)
