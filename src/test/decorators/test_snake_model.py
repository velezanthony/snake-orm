"""@snake_model: it compiles the model, makes it instantiable and stores its metadata.

The constructor is keyword-only (kw_only), as in most modern ORMs.
"""

from __future__ import annotations

import pytest

from snakeorm.decorators import snake_model, snake_table
from snakeorm.fields import SnakeColumn, snake_auto, snake_column, snake_int, snake_str

from snakeorm.model import SnakeModel
from snakeorm.registry import registry


@snake_model
class User:
    """Test model."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    username: SnakeColumn[str] = snake_str()
    active: SnakeColumn[bool] = snake_column(default=True)


def test_compiles_and_stores_table() -> None:
    """@snake_model compiles the model and stores its SnakeTableInfo."""
    assert snake_table(User).name == "users"


def test_instantiation_stores_values() -> None:
    """The model can be instantiated and it keeps the values."""
    user = User(id=1, username="Ana")
    assert user.id == 1
    assert user.username == "Ana"


def test_missing_required_argument_raises() -> None:
    """Leaving out a required argument raises TypeError."""
    with pytest.raises(TypeError):
        User(id=1)  # type: ignore[call-arg]  # username is missing


def test_instances_are_independent() -> None:
    """Two instances share no values."""
    a = User(id=1, username="Ana")
    b = User(id=2, username="Bob")
    assert a.username == "Ana"
    assert b.id == 2


def test_default_used_when_omitted() -> None:
    """A column with a default is optional and falls back to its value when left out."""
    user = User(id=1, username="Ana")
    assert user.active is True


def test_default_can_be_overridden() -> None:
    """The default can be overridden while constructing."""
    user = User(id=1, username="Ana", active=False)
    assert user.active is False


@snake_model(table="people", schema="app")
class Person:
    """Model with a parametrised decorator: it overrides table and schema."""

    id: SnakeColumn[int] = snake_int(primary_key=True)


def test_table_override() -> None:
    """@snake_model(table=...) overrides the table name."""
    assert snake_table(Person).name == "people"


def test_schema_override() -> None:
    """@snake_model(schema=...) overrides the schema."""
    assert snake_table(Person).schema == "app"


def test_parametrized_model_instantiates() -> None:
    """A model with a parametrised decorator instantiates just the same."""
    person = Person(id=5)
    assert person.id == 5


@snake_model(prefix="shoptest")
class Gadget(SnakeModel):
    """Model with a prefix: the table is `{prefix}_{table}`."""

    id: SnakeColumn[int] = snake_int(primary_key=True)


@snake_model(prefix="shoptest", table="items")
class Widget(SnakeModel):
    """Model with prefix + table: both halves change."""

    id: SnakeColumn[int] = snake_int(primary_key=True)


@snake_model(prefix="autotest")
class Ticket(SnakeModel):
    """Model whose autoincrement PK is declared with snake_auto, hence out of the constructor."""

    id: SnakeColumn[int] = snake_auto()
    title: SnakeColumn[str] = snake_str()


def test_autoincrement_pk_is_excluded_from_init() -> None:
    """It instantiates WITHOUT the autoincrement PK: the DB generates that one."""
    ticket = Ticket(title="incidencia")
    assert ticket.title == "incidencia"


def test_passing_autoincrement_pk_is_rejected() -> None:
    """Passing the autoincrement PK to the constructor is an unexpected argument."""
    with pytest.raises(TypeError):
        Ticket(id=1, title="x")  # type: ignore[call-arg]


def test_prefix_prepended_to_default_table() -> None:
    """The prefix is prepended to the default table name."""
    assert snake_table(Gadget).name == "shoptest_gadgets"


def test_prefix_with_custom_table() -> None:
    """prefix + table compose into `{prefix}_{table}`."""
    assert snake_table(Widget).name == "shoptest_items"


@snake_model
class Country(SnakeModel):
    """Model with a table comment declared in its body."""

    id: SnakeColumn[int] = snake_int(primary_key=True)

    SnakeComment = "Countries of the world."


def test_table_comment_from_snake_comment() -> None:
    """The SnakeComment of the body turns into the db_comment of the table."""
    assert snake_table(Country).db_comment == "Countries of the world."


def test_no_snake_comment_defaults_to_none() -> None:
    """With no SnakeComment, the table comment is None."""
    assert snake_table(User).db_comment is None


def test_model_auto_registers() -> None:
    """@snake_model registers the model in the global registry."""
    assert User in registry.models()
