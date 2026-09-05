"""SQLite introspection: the ORM creates the schema and the ORM reads it back.

It is the hardest test that can be run on it, and the same one the Postgres introspector already
passes: if the emitter writes something the reader cannot see, that is a hole — and one no
scaffolding test catches, because they all start from a hand-written schema and check only what they
know to look for.

With that set up, drift comes for free: code and database are the SAME thing, so `drift(...)` has to
be empty. If it says anything, either the introspector is lying or the DDL is.

It runs without a server: SQLite ships in the stdlib.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SQLiteDialect,
    SQLiteDriver,
    SnakeColumn,
    SnakeModel,
    SnakeToOne,
    snake_auto,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
    snake_to_one,
)
from snakeorm.introspection import SQLiteIntrospector, drift
from snakeorm.metadata import SnakeIndexInfo
from snakeorm.migration import emit_create_index, emit_create_table
from snakeorm.registry import SnakeRegistry

_REG = SnakeRegistry()
_DIALECT = SQLiteDialect()


@snake_model(table="lit_customers", registry=_REG)
class Customer(SnakeModel):
    """With an autoincrement PK, a unique column and an optional one."""

    id: SnakeColumn[int] = snake_auto()
    email: SnakeColumn[str] = snake_str(unique=True)
    apodo: SnakeColumn[str | None] = snake_str()


@snake_model(table="lit_orders", registry=_REG)
class Order(SnakeModel):
    """With a foreign key pointing at the customer."""

    id: SnakeColumn[int] = snake_auto()
    customer_id: SnakeColumn[int] = snake_int()
    customer: SnakeToOne[Customer] = snake_to_one(customer_id)


# Unlinked, the relation has no RESOLVED target and the FK cannot be written inside the
# `CREATE TABLE` — which on SQLite is the only window there is.
snake_link(_REG)


@pytest.fixture
def read_back() -> Iterator[dict[str, object]]:
    """Creates the schema with the ORM's OWN DDL and returns what the introspector reads."""
    driver = SQLiteDriver.connect(":memory:")
    for model in (Customer, Order):
        table = _REG.table_of(model)
        assert table is not None
        driver.execute(emit_create_table(table, _DIALECT), ())
    index = SnakeIndexInfo(columns=("apodo",), name="ix_lit_customers_apodo")
    customer = _REG.table_of(Customer)
    assert customer is not None
    driver.execute(emit_create_index(customer, index, _DIALECT), ())
    driver.commit()
    try:
        yield {table.name: table for table in SQLiteIntrospector(driver).tables()}
    finally:
        driver.close()


def test_every_table_and_column_comes_back(read_back: dict[str, object]) -> None:
    """Nothing is lost along the way: both tables and all their columns."""
    assert set(read_back) == {"lit_customers", "lit_orders"}
    columns = [c.name for c in read_back["lit_customers"].columns]  # type: ignore[attr-defined]

    assert columns == ["id", "email", "apodo"]


def test_nullability_and_uniqueness_come_back(read_back: dict[str, object]) -> None:
    """Nullability and uniqueness come back: they are what breaks inserts when misread."""
    clients = read_back["lit_customers"]
    email = clients.get_column("email")  # type: ignore[attr-defined]
    apodo = clients.get_column("apodo")  # type: ignore[attr-defined]

    assert email is not None and email.unique is True and email.nullable is False
    assert apodo is not None and apodo.unique is False and apodo.nullable is True


def test_the_primary_key_and_autoincrement_come_back(
    read_back: dict[str, object],
) -> None:
    """The PK comes back, and `INTEGER PRIMARY KEY` is recognised as autoincrement.

    In SQLite autoincrement is not a keyword: it is that an `INTEGER PRIMARY KEY` aliases the
    internal ROWID. Misreading it would make the scaffolding generate a model demanding the `id` in
    the constructor when the database supplies it by itself.
    """
    clients = read_back["lit_customers"]

    assert [c.name for c in clients.primary_key.columns] == ["id"]  # type: ignore[attr-defined]
    identifier = clients.get_column("id")  # type: ignore[attr-defined]
    assert identifier is not None and identifier.autoincrement is True


def test_the_declared_index_comes_back_and_the_implicit_ones_do_not(
    read_back: dict[str, object],
) -> None:
    """The index somebody DECLARED comes back, not those SQLite creates to back a UNIQUE.

    Reporting the implicit ones would make `check` see drift in a schema the ORM itself has just
    created — a warning that is always false gets learned as noise, and then it stops warning.
    """
    names = [i.name for i in read_back["lit_customers"].indexes]  # type: ignore[attr-defined]

    assert names == ["ix_lit_customers_apodo"]


def test_the_foreign_key_comes_back_with_its_columns(
    read_back: dict[str, object],
) -> None:
    """The FK comes back with its column pair: that is what the scaffolding has to reproduce."""
    relations = read_back["lit_orders"].relationships  # type: ignore[attr-defined]

    assert len(relations) == 1
    assert relations[0].target == "lit_customers"
    assert relations[0].foreign_key.pairs == (("customer_id", "id"),)


def test_there_is_no_drift_against_what_created_it(
    read_back: dict[str, object],
) -> None:
    """THE ACID TEST: the code and the database are the SAME, so there can be no drift.

    If `drift` says anything here, either the introspector reads wrong or the DDL writes something
    else. There is no third explanation, and that is why this test is worth all the previous ones
    put together.
    """
    declared = [_REG.table_of(Customer), _REG.table_of(Order)]

    assert drift(declared, list(read_back.values()), SQLiteDialect()) == []  # type: ignore[arg-type]
