"""The compiler, columns only: a class holding descriptors → SnakeTableInfo.

The type comes from the annotation; `nullable` is inferred from `| None`; the PK is mandatory.
"""

from __future__ import annotations

import pytest

from snakeorm.compiler import compile_model
from snakeorm.fields import SnakeColumn, snake_int, snake_str


class User:
    """Test model (no @snake_model; it is compiled directly)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    username: SnakeColumn[str] = snake_str()
    email: SnakeColumn[str | None] = snake_str()
    age: SnakeColumn[int] = snake_int(name="age")


def test_table_name_is_lower_plural() -> None:
    """The table name is the class name lowercased plus an s."""
    assert compile_model(User).name == "users"


def test_columns_capture_python_type() -> None:
    """Every column captures its Python type from the annotation."""
    column = compile_model(User).get_column("username")
    assert column is not None
    assert column.python_type is str


def test_nullable_inferred_from_optional() -> None:
    """nullable is inferred from `| None`, which is type-first all the way."""
    table = compile_model(User)
    email = table.get_column("email")
    username = table.get_column("username")
    assert email is not None and email.nullable is True
    assert username is not None and username.nullable is False


def test_primary_key_collected() -> None:
    """The columns marked primary_key=True are the ones forming the primary key."""
    pk = compile_model(User).primary_key
    assert [c.name for c in pk.columns] == ["id"]


def test_column_captures_attr_name_equal_to_sql_when_no_override() -> None:
    """With no override, the attribute name matches the SQL name."""
    column = compile_model(User).get_column("username")
    assert column is not None
    assert column.attr_name == "username"


def test_column_captures_attr_name_distinct_from_sql_on_override() -> None:
    """With `name=`, the metadata keeps the Python attribute apart from the SQL name.

    That is what makes the trip back SQL→Python possible (mapping rows onto models).
    """
    table = compile_model(User)
    age = table.get_column("age")
    assert age is not None
    assert age.name == "age"  # the SQL name
    assert age.attr_name == "age"  # the Python attribute


def test_model_without_pk_fails() -> None:
    """A model with no PK fails to compile: fail-fast."""

    class NoPk:
        name: SnakeColumn[str] = snake_str()

    with pytest.raises(ValueError):
        compile_model(NoPk)
