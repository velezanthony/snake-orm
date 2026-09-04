"""Inheritance from an abstract base: shared columns, one table per child.

This feature ALREADY EXISTED —`collect_inherited` walks the MRO— but it was neither declared nor
documented: the signal for "this one is a base" was NOT putting the decorator on it, which is to
say an absence. And an absence cannot be read, nor checked.

`@snake_abstract` changes no behaviour: it DECLARES it, and in exchange the ORM gets to say
something useful when somebody treats the base as a table.
"""

from __future__ import annotations


import pytest

from snakeorm import (
    PostgresDialect,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeUtc,
    snake_abstract,
    snake_datetimetz,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.core.exceptions import SnakeRegistryError
from snakeorm.migration import emit_create_table
from snakeorm.migration.autodetect import current_schema
from snakeorm.registry import registry


@snake_abstract
class Auditable(SnakeModel):
    """The base: it contributes columns to whoever inherits it, and is no table."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    created: SnakeColumn[SnakeUtc] = snake_datetimetz()


@snake_model(table="abs_orders")
class Order(Auditable):
    """Inherits both columns and adds one of its own."""

    amount: SnakeColumn[int] = snake_int()


@snake_model(table="abs_customers")
class Customer(Auditable):
    """Same thing in ANOTHER table: the columns are duplicated, never shared."""

    name: SnakeColumn[str] = snake_str()


def test_each_child_gets_the_inherited_columns_in_its_own_table() -> None:
    """The base's columns show up in EVERY child table, not in one shared table."""
    order = [column.name for column in snake_table(Order).columns]
    customer = [column.name for column in snake_table(Customer).columns]

    assert order == ["id", "created", "amount"]
    assert customer == ["id", "created", "name"]


def test_the_base_columns_come_first() -> None:
    """Inherited first and own ones after: the DDL reads better and the order is stable.

    This is no whim: were it to depend on the MRO order or on a `set`, two runs could generate
    different migrations for the very same model.
    """
    ddl = emit_create_table(snake_table(Order), PostgresDialect())

    assert ddl.index('"id"') < ddl.index('"created"') < ddl.index('"amount"')


def test_the_abstract_base_is_not_migratable() -> None:
    """The base does NOT show up in the schema: unregistered, so the migrations never see it."""
    names = [table.name for table in current_schema(registry)]

    assert "abs_orders" in names and "abs_customers" in names
    assert registry.table_of(Auditable) is None


def test_querying_the_base_says_what_it_actually_is() -> None:
    """The message tells an abstract base apart from an oversight, which is the point of the mark.

    Without it, the generic error suggested `@snake_model` — that is, it sent you off to turn into a
    table the very thing that exists in order not to be one. A message pointing the opposite way is
    worse than a vague one.
    """
    with pytest.raises(SnakeRegistryError, match="is an abstract base"):
        SnakeQuery(Auditable)


def test_a_child_overriding_a_column_wins_without_duplicating_it() -> None:
    """If the child redefines an inherited column, its own wins and NOTHING is duplicated.

    What gets redefined is the METADATA (here, the SQL name), not the type: changing the type of an
    inherited column violates Liskov and the checker rejects it, rightly —a child cannot widen what
    the base promised—. That the ORM would allow it but the type would not is exactly the right
    division of labour.
    """

    @snake_model(table="abs_especial")
    class Especial(Auditable):
        """Same column, another name in the database."""

        created: SnakeColumn[SnakeUtc] = snake_datetimetz(name="created_at")

    columns = [column.name for column in snake_table(Especial).columns]

    assert columns == ["id", "created_at"], "the child's wins, and is not duplicated"


def test_the_mark_is_not_inherited() -> None:
    """The mark is not inherited: a concrete child cannot look abstract.

    Were it inherited, the help message would say the opposite of what is happening — and a model
    that IS a table would be described as though it were not.
    """
    from snakeorm.decorators.abstract import is_abstract

    assert is_abstract(Auditable) is True
    assert is_abstract(Order) is False
