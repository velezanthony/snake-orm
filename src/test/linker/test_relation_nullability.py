"""Tests for PARITY between the nullability of the FK and that of its to-one relation.

The hole they close, and it was a type lie in the fullest sense:

    brand_id: SnakeColumn[int | None] = snake_int()          # the FK may be NULL
    brand:    SnakeToOne[Brand]       = snake_to_one(brand_id)

With the FK at NULL, `include()` does a LEFT JOIN, finds no match and the ORM hangs `None` off the
relation — which is the right thing. But the type says `Brand`, so `car.brand.name` COMPILES
and in production it is an `AttributeError`. The checker approved a line the runtime cannot honour.

The answer is not for the ORM to invent an empty object nor to keep quiet: it is for the ANNOTATION
to tell the truth. If the FK accepts NULL, the relation is declared `SnakeToOne[Brand | None]` and
then mypy and pyright force you to handle the `None` — checked, both reject it. And if the two do
not agree, the linker SHOUTS at link time, which is before a single row exists.
"""

# WITHOUT `from __future__ import annotations` on purpose: the models are declared INSIDE each test
# (every scenario needs its own registry), and with deferred annotations `get_type_hints` would
# resolve them against the module globals, where a local class does not exist.

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToOne,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
    snake_to_one,
)
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.registry import SnakeRegistry


@pytest.fixture
def reg() -> SnakeRegistry:
    """A registry of its own: linking is global, and these tests declare deliberately broken models."""
    return SnakeRegistry()


def test_an_optional_relation_links_against_its_target(reg: SnakeRegistry) -> None:
    """Checks that `SnakeToOne[M | None]` resolves its target just like `SnakeToOne[M]`.

    Without unwrapping the `| None`, the linker tried to read `__name__` off a `types.UnionType` and
    blew up with an `AttributeError` from its own guts: declaring the truth was impossible.
    """

    @snake_model(table="brands", registry=reg)
    class Brand(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        name: SnakeColumn[str] = snake_str()

    @snake_model(table="cars", registry=reg)
    class Car(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        brand_id: SnakeColumn[int | None] = snake_int()
        brand: SnakeToOne[Brand | None] = snake_to_one(brand_id)

    snake_link(reg)
    table = reg.table_of(Car)
    assert table is not None
    relation = next(r for r in table.relationships if r.name == "brand")
    assert relation.target == "Brand"


def test_a_nullable_fk_with_a_non_optional_relation_is_rejected(
    reg: SnakeRegistry,
) -> None:
    """Checks that an FK accepting NULL with a NON optional relation fails at link time.

    It is the combination that lied: the runtime returns `None` and the type promises an object.
    """

    @snake_model(table="brands", registry=reg)
    class Brand(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)

    @snake_model(table="cars", registry=reg)
    class Car(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        brand_id: SnakeColumn[int | None] = snake_int()
        brand: SnakeToOne[Brand] = snake_to_one(brand_id)

    with pytest.raises(SnakeModelDefinitionError, match="None"):
        snake_link(reg)


def test_a_non_nullable_fk_with_an_optional_relation_is_rejected(
    reg: SnakeRegistry,
) -> None:
    """Checks that parity is demanded in BOTH directions.

    With a `NOT NULL` FK there is always a match, so the relation is never `None`. Declaring it
    optional would force handling an impossible case: noise the checker imposes and that hides the
    `None` values that do matter.
    """

    @snake_model(table="brands", registry=reg)
    class Brand(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)

    @snake_model(table="cars", registry=reg)
    class Car(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        brand_id: SnakeColumn[int] = snake_int()
        brand: SnakeToOne[Brand | None] = snake_to_one(brand_id)

    with pytest.raises(SnakeModelDefinitionError, match="None"):
        snake_link(reg)


def test_the_error_names_both_sides(reg: SnakeRegistry) -> None:
    """Checks that the message names the FK column and the relation, not just that something fails.

    A parity error that does not say which two things disagree forces you to hunt them down by hand.
    """

    @snake_model(table="brands", registry=reg)
    class Brand(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)

    @snake_model(table="cars", registry=reg)
    class Car(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        brand_id: SnakeColumn[int | None] = snake_int()
        brand: SnakeToOne[Brand] = snake_to_one(brand_id)

    with pytest.raises(SnakeModelDefinitionError) as caught:
        snake_link(reg)
    mensaje = str(caught.value)
    assert "brand_id" in mensaje
    assert "brand" in mensaje


def test_a_composite_fk_takes_the_nullability_of_the_whole_key(
    reg: SnakeRegistry,
) -> None:
    """Checks that with a COMPOSITE FK it is enough for ONE column to accept NULL.

    A composite key with a member at NULL matches no row at all, so the relation can come back
    `None` just like with a simple FK. Demanding that ALL of them be nullable would let the mixed
    case through, which is the one that bites.
    """

    @snake_model(table="brands", registry=reg)
    class Brand(SnakeModel):
        pais: SnakeColumn[str] = snake_str(primary_key=True)
        codigo: SnakeColumn[int] = snake_int(primary_key=True)

    @snake_model(table="cars", registry=reg)
    class Car(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        brand_pais: SnakeColumn[str] = snake_str()
        brand_codigo: SnakeColumn[int | None] = snake_int()  # only ONE accepts NULL
        brand: SnakeToOne[Brand] = snake_to_one(brand_pais, brand_codigo)

    with pytest.raises(SnakeModelDefinitionError, match="None"):
        snake_link(reg)


# Declared at MODULE level, unlike every model above: this one has to RUN, and both the session and
# `SnakeQuery` resolve through the global registry.
@snake_model(table="nn_depots")
class _Depot(SnakeModel):
    """The far end of a nullable relation."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    city: SnakeColumn[str] = snake_str()


@snake_model(table="nn_vans")
class _Van(SnakeModel):
    """One van with a depot and one without: the LEFT JOIN finds nobody for the second."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    plate: SnakeColumn[str] = snake_str()
    depot_id: SnakeColumn[int | None] = snake_int()
    depot: SnakeToOne[_Depot | None] = snake_to_one(depot_id)


def test_a_left_join_with_no_match_answers_None_and_not_a_hollow_object() -> None:
    """The nullable relation RUN, not just annotated: no match gives `None`, never an empty object.

    Every other test here checks the ANNOTATION — that `depot` is typed `_Depot | None`. None of them
    runs a query, so this module's own promise —"the answer is not that the ORM invents an empty
    object"— had no row behind it: forcing `_pk_is_null` to `False` passed all 3.955 tests with both
    engines up. The emitted SQL is identical either way, so only a VALUE can tell them apart.
    """
    from snakeorm.dialects import SQLiteDialect
    from snakeorm.drivers import SQLiteDriver
    from snakeorm.linker import snake_link
    from snakeorm.migration import emit_create_table
    from snakeorm.query import SnakeQuery
    from snakeorm.session import SnakeSession

    from snakeorm import snake_table

    snake_link()
    dialect = SQLiteDialect()
    driver = SQLiteDriver.connect(":memory:")
    for model in (_Depot, _Van):
        driver.execute(emit_create_table(snake_table(model), dialect), ())
    driver.commit()

    session = SnakeSession(driver, dialect)
    session.add(_Depot(id=1, city="Vigo"))
    session.add(_Van(id=1, plate="VAN-1", depot_id=1))
    session.add(_Van(id=2, plate="VAN-2", depot_id=None))
    session.commit()

    vans = session.all(SnakeQuery(_Van).include(_Van.depot).order_by(_Van.id.asc()))

    assert vans[0].depot is not None and vans[0].depot.city == "Vigo"
    assert vans[1].depot is None
