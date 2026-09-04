"""A `@snake_result` scalar declared `X | None` compiles down to `X`: the nullable is unwrapped.

Without this, the user had no CORRECT way of declaring a nullable aggregate:

- `avg: float`        -> the coercion works, but the type lies the moment the AVG is NULL
  (SUM/AVG/MIN/MAX over zero rows are NULL in SQL; only COUNT is 0).
- `avg: float | None` -> the type is honest, but `float | None` is not a key of the converter
  registry, so the coercion was NOT applied and a psycopg2 `Decimal` came through.

The Optional is unwrapped while compiling the `@snake_result`, exactly as the compiler does with the
model's columns. The `None` value survives untouched: `coerce` never touches nulls.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from snakeorm.decorators import SnakeResult, snake_model, snake_result
from snakeorm.decorators.result import snake_result_info
from snakeorm.fields import SnakeColumn, snake_int

from snakeorm.model import SnakeModel
from snakeorm.session.coercion import coerce


@snake_model(table="sro_widgets")
class Widget(SnakeModel):
    """Minimal base model for the result classes of this module."""

    id: SnakeColumn[int] = snake_int(primary_key=True)


@snake_result
class PlainStats(SnakeResult[Widget]):
    """Non-nullable scalars."""

    widget: Widget
    total: int


@snake_result
class OptionalStats(SnakeResult[Widget]):
    """Nullable scalars: the right call for an AVG or a SUM, which are NULL over zero rows."""

    widget: Widget
    average: float | None
    biggest: int | None


def test_plain_scalar_keeps_its_type() -> None:
    """A non-nullable scalar compiles exactly as it is."""
    assert snake_result_info(PlainStats).scalars == (("total", int),)


def test_optional_scalar_is_unwrapped() -> None:
    """`float | None` compiles to `float`: that is the key the converter is looked up under."""
    assert snake_result_info(OptionalStats).scalars == (
        ("average", float),
        ("biggest", int),
    )


@pytest.mark.parametrize(
    ("value", "expected_type"),
    [(Decimal("2.5"), float), (2.5, float)],
)
def test_optional_scalar_still_coerces(value: object, expected_type: type) -> None:
    """With the type unwrapped the coercion does apply: a `Decimal` turns into a `float`."""
    _, declared = snake_result_info(OptionalStats).scalars[0]
    assert type(coerce(value, declared)) is expected_type


def test_null_survives_an_optional_scalar() -> None:
    """An `AVG` over zero rows is NULL: the None crosses the coercion untouched."""
    _, declared = snake_result_info(OptionalStats).scalars[0]
    assert coerce(None, declared) is None
