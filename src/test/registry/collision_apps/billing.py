"""Billing app: it has ITS OWN Customer, and a Invoice that references it."""

from __future__ import annotations

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToOne,
    snake_int,
    snake_model,
    snake_str,
    snake_to_one,
)
from test.registry.collision_apps import apps_registry


@snake_model(table="col_fact_customers", registry=apps_registry)
class Customer(SnakeModel):
    """The BILLING customer: the real target of the relation below."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    nif: SnakeColumn[str] = snake_str()


@snake_model(table="col_invoices", registry=apps_registry)
class Invoice(SnakeModel):
    """References the Customer of THIS module, and no other."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    customer_id: SnakeColumn[int] = snake_int()
    customer: SnakeToOne[Customer] = snake_to_one(customer_id)
