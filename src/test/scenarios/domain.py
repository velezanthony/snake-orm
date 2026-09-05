"""Scenario domain: @snake_model models covering every known edge case.

This is the "test project inside the tests": a rich database to develop against in
parallel (JOINs, migrations, serial PK...). Each model exercises a different case:

- Country: simple PK + UNIQUE column.
- Brand/Car/Owner: chain of FKs (Owner→Car→Brand→Country) for the future DEEP navigation.
- Owner: name override (full_name), NULLABLE column (age) and one with a DEFAULT (active).
- OrderItem: COMPOSITE PK.
- Event: assorted types (UUID, Decimal, datetime) + nullable column.

Note: the FKs are plain int columns for now; once JOINs exist they will become snake_to_one.
"""

from __future__ import annotations

from snakeorm import SnakeUtc, snake_datetimetz

from decimal import Decimal
from uuid import UUID

from snakeorm.decorators import snake_model
from snakeorm.fields import SnakeColumn, snake_column, snake_int, snake_str


@snake_model(table="countries")
class Country:
    """Country. Simple PK + unique ISO code."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    iso_code: SnakeColumn[str] = snake_str(unique=True)


@snake_model(table="brands")
class Brand:
    """Brand. FK to country (a plain column for now)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    country_id: SnakeColumn[int] = snake_int()


@snake_model(table="cars")
class Car:
    """Car. FK to brand."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    model: SnakeColumn[str] = snake_str()
    brand_id: SnakeColumn[int] = snake_int()


@snake_model(table="owners")
class Owner:
    """Owner. Edge cases: name override, nullable column and column with a default."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(name="full_name")  # SQL override != attribute
    age: SnakeColumn[int | None] = snake_int()  # nullable
    active: SnakeColumn[bool] = snake_column(default=True)  # default
    car_id: SnakeColumn[int] = snake_int()


@snake_model(table="order_items")
class OrderItem:
    """Order line. COMPOSITE PK (order_id, product_id)."""

    order_id: SnakeColumn[int] = snake_int(primary_key=True)
    product_id: SnakeColumn[int] = snake_int(primary_key=True)
    quantity: SnakeColumn[int] = snake_int()


@snake_model(table="events")
class Event:
    """Event. Assorted types: UUID (PK), Decimal, datetime, and a nullable note."""

    id: SnakeColumn[UUID] = snake_column(primary_key=True)
    amount: SnakeColumn[Decimal] = snake_column()
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz()
    note: SnakeColumn[str | None] = snake_str()
