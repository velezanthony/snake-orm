"""Scalars from `annotate()` are coerced to the type declared in the `@snake_result`.

Until now `select()` did coerce and `annotate()` did not: aggregates came back exactly as the
driver handed them over. And the driver lies: Postgres computes `AVG(...)` as `numeric`, which
psycopg2 delivers as a `Decimal`. A result class declaring `avg: float` was getting a `Decimal`,
meaning the promised type and the actual value did not match — precisely what this ORM exists to
prevent.

The source of truth is the `@snake_result` annotation, not the aggregate: the user declared the
type.
"""

from __future__ import annotations

from decimal import Decimal

from snakeorm.session.coercion import coerce


def test_decimal_becomes_float_when_float_is_declared() -> None:
    """A `Decimal` (what psycopg2 returns for an AVG) is coerced to the declared `float`."""
    value = coerce(Decimal("2.5"), float)
    assert value == 2.5
    assert isinstance(value, float)


def test_float_coercion_is_idempotent() -> None:
    """Coercing a `float` that is already a `float` leaves it alone (holds for any driver)."""
    assert coerce(2.5, float) == 2.5
    assert isinstance(coerce(2.5, float), float)


def test_int_is_not_forced_to_float() -> None:
    """An integer declared `int` stays an `int`: the float converter is not applied to it."""
    value = coerce(3, int)
    assert value == 3
    assert isinstance(value, int)


def test_null_survives_coercion() -> None:
    """`SUM` over zero rows is NULL in SQL: a None declared float stays None."""
    assert coerce(None, float) is None
