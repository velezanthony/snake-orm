"""The SnakeColumn descriptor and the snake_column specifier.

Class access → SnakeExpr (for queries); instance access → the stored value. The column name defaults
to the property name, and a rename is supported.
"""

from __future__ import annotations

from typing import Any

from snakeorm.expressions import SnakeExpr
from snakeorm.fields import SnakeColumn, snake_column


class _Model:
    """Test model (no @snake_model, so the descriptor is exercised in isolation)."""

    id: SnakeColumn[int] = snake_column(primary_key=True, db_comment="clave primaria")
    username: SnakeColumn[str] = snake_column()
    age: SnakeColumn[int] = snake_column(name="age")


def _descriptor(name: str) -> Any:
    """Returns the raw descriptor (not the SnakeExpr that class access hands back)."""
    return _Model.__dict__[name]


def test_class_access_returns_expr() -> None:
    """Class access returns a SnakeExpr carrying the column path."""
    expr = _Model.username
    assert isinstance(expr, SnakeExpr)
    assert expr.path == ("username",)


def test_class_access_uses_name_override() -> None:
    """A rename (name=...) shows up in the path of the expression."""
    assert _Model.age.path == ("age",)


def test_instance_access_returns_stored_value() -> None:
    """Instance access returns the value that was assigned."""
    model = _Model()
    model.username = "Ana"
    assert model.username == "Ana"


def test_no_leak_between_instances() -> None:
    """Two instances share no values: the storage is per instance."""
    a = _Model()
    b = _Model()
    a.username = "Ana"
    b.username = "Bob"
    assert a.username == "Ana"
    assert b.username == "Bob"


def test_descriptor_exposes_metadata_for_compiler() -> None:
    """The descriptor exposes the metadata the compiler is going to read."""
    id_column = _descriptor("id")
    assert id_column.primary_key is True
    assert id_column.db_comment == "clave primaria"
    assert id_column.column_name == "id"


def test_column_name_defaults_to_property_name() -> None:
    """With no rename, the column name is the name of the property."""
    assert _descriptor("username").column_name == "username"
