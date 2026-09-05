"""@snake_row: a typed ROW container for session.call(), with NO base model.

Unlike @snake_result (which demands EXACTLY one @snake_model field), @snake_row is scalar from end
to end: it is the DECLARED shape expected out of a database function or procedure (opaque SQL). The
decorator turns the class into a dataclass (so dataclass_transform types the __init__), keeps the
order and type of its fields, and unwraps `X | None` down to `X`.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from snakeorm.decorators import SnakeRow, snake_row
from snakeorm.decorators.row import snake_row_info
from snakeorm.core.exceptions import SnakeModelDefinitionError


@snake_row
class _Payroll(SnakeRow):
    """Declared row of a payroll function: scalars only, no base model."""

    employee_id: int
    gross: Decimal
    net: Decimal


def test_row_is_constructible_with_its_scalars() -> None:
    """@snake_row generates an __init__ (dataclass) that accepts every scalar field."""
    row = _Payroll(employee_id=1234, gross=Decimal("2000"), net=Decimal("1600"))
    assert (row.employee_id, row.gross, row.net) == (
        1234,
        Decimal("2000"),
        Decimal("1600"),
    )


def test_row_stores_columns_in_declaration_order() -> None:
    """It keeps the (name, type) list of fields in declaration order, for the positional mapping."""
    info = snake_row_info(_Payroll)
    assert info.columns == (
        ("employee_id", int),
        ("gross", Decimal),
        ("net", Decimal),
    )


def test_row_unwraps_optional_scalars() -> None:
    """A scalar declared `X | None` compiles down to `X` (the coercion key); the None survives."""

    @snake_row
    class _WithOptional(SnakeRow):
        code: str
        badge: UUID | None

    info = snake_row_info(_WithOptional)
    assert info.columns == (("code", str), ("badge", UUID))


def test_row_without_base_is_rejected() -> None:
    """A class that does NOT inherit from SnakeRow is no good to session.call(): it fails loudly
    right at decoration time."""
    with pytest.raises(
        SnakeModelDefinitionError, match="does not inherit from SnakeRow"
    ):

        @snake_row
        class _NoBase:  # does not inherit SnakeRow
            x: int


def test_non_row_class_has_no_info() -> None:
    """snake_row_info over a class that is not a @snake_row fails loudly."""
    with pytest.raises(SnakeModelDefinitionError, match="is not a @snake_row"):
        snake_row_info(object)
