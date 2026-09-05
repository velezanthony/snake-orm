"""Example domain that exercises EVERYTHING built across the six phases.

This is not a toy demo: it is the model used by the full flow of `test_full_flow_e2e.py`
—migrations really generated, really applied and really queried—. If anything that was built
does not fit once it is used together, this is where it shows.

What it exercises, and which phase it comes from:

- `snake_enum` with `storage=CHECK` (0.5) and the CHECKs derived from it (0.4)
- `snake_check` declared outside the class body (0.4)
- a PARTIAL index, which is the exception to uniqueness (1.1)
- `db_comment` on a table and on a column, which used to be dead metadata (1.2)
- `NUMERIC(12,2)` with precision and scale (1.8)
- a to-one relationship with `on_delete` (1.3)
- a model on ANOTHER connection (4.2)
"""

from __future__ import annotations

from decimal import Decimal
from enum import IntEnum, StrEnum

from snakeorm import (
    SnakeColumn,
    SnakeIndex,
    SnakeModel,
    SnakeServerDefault,
    SnakeToOne,
    SnakeUtc,
    snake_auto,
    snake_check,
    snake_checks,
    snake_datetimetz,
    snake_decimal,
    snake_enum,
    snake_indexes,
    snake_int,
    snake_model,
    snake_str,
    snake_to_one,
)


class OrderStatus(StrEnum):
    """The lifecycle state of a `Order`."""

    NEW = "new"
    PAID = "paid"
    SHIPPED = "shipped"


class Priority(IntEnum):
    """Handling priority, sortable as a number."""

    NORMAL = 1
    URGENT = 10


@snake_model(table="shop_customers")
class Customer(SnakeModel):
    """A customer of the store."""

    SnakeComment = "Customers registered in the store"

    id: SnakeColumn[int] = snake_auto()
    email: SnakeColumn[str] = snake_str(unique=True, db_comment="Login email")
    name: SnakeColumn[str] = snake_str()
    # Soft-delete: the column that justifies the partial index below.
    baja: SnakeColumn[SnakeUtc | None] = snake_datetimetz()


@snake_model(table="shop_orders")
class Order(SnakeModel):
    """A `Order` with a state enum, a numeric priority and an amount with two decimals."""

    id: SnakeColumn[int] = snake_auto()
    customer_id: SnakeColumn[int] = snake_int()
    customer: SnakeToOne[Customer] = snake_to_one(customer_id)
    status: SnakeColumn[OrderStatus] = snake_enum(OrderStatus, default=OrderStatus.NEW)
    priority: SnakeColumn[Priority] = snake_enum(Priority, default=Priority.NORMAL)
    amount: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)
    created: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )

    SnakeIndexes = [SnakeIndex(customer_id)]


# Outside the class body: inside it, `amount` is the raw descriptor and does not know its name yet.
# `Decimal("0")` and not `0`: the checker refuses to mix Decimal with int, and it is right —that is
# exactly where money bugs come from—. That is the typing working, not an annoyance.
snake_checks(
    Order,
    snake_check(Order.amount > Decimal("0"), name="ck_shop_orders_amount_positive"),
)

# PARTIAL index: it only indexes the ACTIVE customers, which is what makes the soft-delete usable.
# It goes through `snake_indexes` and not in the class body for the same reason as the checks: a
# condition needs the name of the column, and inside the body the descriptor does not have it yet.
snake_indexes(
    Customer,
    SnakeIndex(
        Customer.name, name="ix_shop_customers_activos", where=Customer.baja.is_null()
    ),
)


@snake_model(table="shop_visits", database="analytics")
class Visit(SnakeModel):
    """Visit log: it lives in ANOTHER database, the analytics one."""

    id: SnakeColumn[int] = snake_auto()
    path: SnakeColumn[str] = snake_str()
    duration_ms: SnakeColumn[int] = snake_int()
