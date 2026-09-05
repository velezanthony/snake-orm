"""Typed navigation and `snake_checks`/`snake_indexes` honour the model's `registry=`.

The review found that `@snake_model(registry=reg)` compiled, but deep navigation (`Car.brand.name`),
collections (`User.cars`) and `snake_checks` resolved against the GLOBAL registry —they returned an
error that LIED ("call snake_link()") even though it was linked in `reg`—.

The fix: the model remembers its registry (`__snake_registry__`) and the descriptors propagate it.
These tests pin the exact scenario of the finding over a registry that is NOT the global one. The
models sit at MODULE level on purpose: `get_type_hints` (which the linker uses) resolves annotations
against the module globals, not against the locals of a function.
"""

from __future__ import annotations

from snakeorm import (
    SnakeColumn,
    SnakeExpr,
    SnakeModel,
    SnakeToMany,
    SnakeToOne,
    snake_check,
    snake_checks,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.dialects import PostgresDialect
from snakeorm.fields.relationship import SnakeCollection
from snakeorm.query import SnakeQuery
from snakeorm.registry import SnakeRegistry

_REG = SnakeRegistry()  # NOT the global one: that is what the bug ignored


@snake_model(table="cr_brands", registry=_REG)
class Brand(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="cr_cars", registry=_REG)
class Car(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    brand_id: SnakeColumn[int] = snake_int()
    brand: SnakeToOne[Brand] = snake_to_one(brand_id)
    owner_id: SnakeColumn[int] = snake_int()
    owner: SnakeToOne[User] = snake_to_one(owner_id)


@snake_model(table="cr_users", registry=_REG)
class User(SnakeModel):
    id: SnakeColumn[int] = snake_int(primary_key=True)
    cars: SnakeToMany[Car] = snake_to_many("owner")  # inverse of Car.owner


snake_link(_REG)


def test_deep_to_one_navigation_resolves_in_the_custom_registry() -> None:
    """Checks `Car.brand.name` over a custom registry: it used to raise AttributeError against the global."""
    expr = Car.brand.name
    assert isinstance(expr, SnakeExpr)
    assert expr.path == ("brand", "name")


def test_collection_access_resolves_in_the_custom_registry() -> None:
    """Checks `User.cars` over a custom registry: it used to raise SnakeUnlinkedRelationship (a lie)."""
    assert isinstance(User.cars, SnakeCollection)


def test_any_navigation_resolves_in_the_custom_registry() -> None:
    """Checks that `.any()` with to-one navigation of the child resolves in the custom registry."""
    exists = User.cars.any(Car.brand.name == "SEAT")
    assert exists is not None


def test_snake_checks_works_on_a_custom_registry_model() -> None:
    """Checks that `snake_checks` over a custom-registry model does not mistake it for 'not a model'."""
    snake_checks(User, snake_check(User.id > 0, name="ck_user_id_pos"))

    table = _REG.table_of(User)
    assert table is not None
    assert any(c.resolved_name(table.name) == "ck_user_id_pos" for c in table.checks)


def test_a_custom_registry_model_can_be_queried() -> None:
    """`SnakeQuery(Car)` over a model in its own registry. It used to refuse, and it MISDIRECTED.

    The error was `Car is not registered: is it missing @snake_model?` — with the decorator right
    there on the class. It sent you to look at the one place where nothing was wrong, while the
    answer (`__snake_registry__`, which the descriptors already read) was one `getattr` away.
    """
    snake_link(_REG)

    query = SnakeQuery(Car)

    assert query.registry is _REG
    assert _REG.table_of(Car) is not None


def test_the_query_resolves_its_joins_in_the_registry_it_carries() -> None:
    """And the registry it carries reaches the EMITTER, which is where a wrong one goes unnoticed.

    Being able to build the query is half the fix; a query that then resolved its JOIN targets in
    the global registry would raise on a model that is not there — or, with a homonym present, join
    a stranger's table and say nothing.
    """
    snake_link(_REG)

    sql, _ = SnakeQuery(Car).filter(Car.brand.name == "x").to_sql(PostgresDialect())

    assert "cr_brands" in sql
