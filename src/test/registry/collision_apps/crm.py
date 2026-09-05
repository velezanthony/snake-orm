"""CRM app: another Customer. Same class name, another table, another concept."""

from __future__ import annotations

from snakeorm import SnakeColumn, SnakeModel, snake_int, snake_model, snake_str

from test.registry.collision_apps import apps_registry


@snake_model(table="col_crm_customers", registry=apps_registry)
class Customer(SnakeModel):
    """The CRM customer: nothing to do with the billing one."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    email: SnakeColumn[str] = snake_str()
