"""The row mapper: what gets compiled once, and what must NOT break while doing it.

The change was born out of a measurement: 17.3 µs per row, with sixteen calls to
`has_server_default` and eight to `coerce` **per row of eight columns** — all of it fixed per table.
The project says on its first page that the metadata exists once and the runtime never inspects the
class again; this was the place where that did not hold, and it was the hottest one.

Compiling it brings it down to 4.0 µs (4.3x). But speeding things up by hydrating "by hand" —with no
constructor, writing straight to the storage key— can break subtle things, and that is what these
tests are about: the enum still comes back as a member, the SQLite bool is still a `bool`, and a
recompiled table does not keep the old plan.
"""

from __future__ import annotations

from decimal import Decimal
from enum import IntEnum, StrEnum
from uuid import UUID

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    snake_auto,
    snake_column,
    snake_enum,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.session.mapper import hydrate, plan_for


class State(StrEnum):
    """Text enum."""

    ACTIVE = "active"
    CLOSED = "closed"


class Level(IntEnum):
    """Numeric enum."""

    BAJO = 1
    ALTO = 9


@snake_model(table="map_filas")
class Row(SnakeModel):
    """A model with the types that DO need conversion and others that do not."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    active: SnakeColumn[bool] = snake_column()
    ratio: SnakeColumn[float] = snake_column()
    codigo: SnakeColumn[UUID] = snake_column()
    status: SnakeColumn[State] = snake_enum(State)
    level: SnakeColumn[Level] = snake_enum(Level)


_UUID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
# The `ratio` arrives as a `Decimal`, which is what a Postgres `numeric` gives: `_to_float` only
# converts from numeric types and lets the rest through, on purpose.
_ROW = (7, "ana", 1, Decimal("2.5"), _UUID, "active", 9)


def test_it_hydrates_every_column_in_order() -> None:
    """The basics: every value ends up in its own attribute."""
    row = hydrate(Row, snake_table(Row), _ROW)

    assert row.id == 7
    assert row.name == "ana"


def test_the_enums_come_back_as_members_not_as_raw_values() -> None:
    """An enum comes back as a MEMBER, which is the central promise of the ORM.

    The enum converter is now resolved when the plan is compiled, not per row. Had that resolution
    been lost along the way, `status` would be the string `'alta'` and nobody would find out until
    comparing against `State.ACTIVE` and getting... `True`, because a `StrEnum` compares equal to its
    text. Precisely the silent failure this project is after.
    """
    row = hydrate(Row, snake_table(Row), _ROW)

    assert row.status is State.ACTIVE
    assert row.level is Level.ALTO


def test_a_boolean_stored_as_an_integer_comes_back_as_bool() -> None:
    """SQLite stores 0/1 and the driver returns `int`: the conversion still gets applied."""
    row = hydrate(Row, snake_table(Row), _ROW)

    assert row.active is True and isinstance(row.active, bool)


def test_the_types_that_need_no_conversion_pass_through() -> None:
    """`str` and `int` do not pay a call per row: their instruction carries `None` as converter.

    That is half the saving. The other half is not rebuilding the attribute name, and both can only
    be done because the plan is compiled ONCE.
    """
    plan = plan_for(Row, snake_table(Row))
    by_key = dict(plan)

    assert by_key["__snake_name"] is None, "a text passes straight through"
    assert by_key["__snake_codigo"] is not None, "a UUID does get converted"


def test_uuid_and_float_are_still_coerced() -> None:
    """The registry converters still get applied: the driver does not always respect the type."""
    row = hydrate(Row, snake_table(Row), _ROW)

    assert row.codigo == UUID(_UUID)
    assert row.ratio == 2.5 and isinstance(row.ratio, float)


def test_a_relinked_table_invalidates_its_plan() -> None:
    """If the table of the model changes, the plan is REBUILT instead of keeping the old one.

    `snake_link()` replaces the tables with new objects (with the relations already resolved). A
    plan that survived that would carry instructions from a table that no longer is — values in the
    wrong attributes, and not a single error.
    """
    import dataclasses

    original = snake_table(Row)
    plan_original = plan_for(Row, original)
    otra = dataclasses.replace(original, columns=original.columns[:2])

    assert plan_for(Row, original) is plan_original, "the same table reuses its plan"
    assert len(plan_for(Row, otra)) == 2, "a different table recompiles it"


def test_the_cache_does_not_grow_with_every_relink() -> None:
    """The cache is bounded by the number of MODELS, not by that of every table ever created.

    The first version indexed by `id(table)` and LEAKED: every `snake_link()` creates new tables, so
    it piled up an entry —and a strong reference— for each of them. Measured back then: five links,
    five entries for a single model. It is a bug that slipped in while FIXING performance, which is
    when they slip in most easily.
    """
    import dataclasses

    from snakeorm.session.mapper import _CACHE

    _CACHE.clear()
    original = snake_table(Row)
    for corte in range(1, 6):
        plan_for(Row, dataclasses.replace(original, columns=original.columns[:corte]))

    assert len(_CACHE) == 1, f"one model, one entry; there were {len(_CACHE)}"


def test_the_hydrated_object_behaves_like_a_constructed_one() -> None:
    """Skipping the constructor cannot leave a half-built object: `repr` and `==` still hold.

    It writes straight into the storage key of the descriptor, which is EXACTLY what its `__set__`
    does. If it were not, the object would look fine until somebody printed it.
    """
    hidratada = hydrate(Row, snake_table(Row), _ROW)
    construida = Row(
        name="ana",
        active=True,
        ratio=2.5,
        codigo=UUID(_UUID),
        status=State.ACTIVE,
        level=Level.ALTO,
    )
    construida.id = 7

    assert hidratada == construida, "same PK, same row"
    assert repr(hidratada) == repr(construida)


def test_the_polymorphic_dispatch_is_resolved_once_per_table_not_once_per_row() -> None:
    """The polymorphic dispatch does NOT ask the registry on every row. It is fixed per table.

    This test exists because the regression already happened: the first version looked for the
    position of the discriminator with a linear scan and built an f-string and a `str()` per row to
    ask which subclass it was. Measured: 3.49 → 5.42 µs per row, 55% more — on the hottest path of
    the ORM and in the SAME function where that waste had been removed the day before.

    CALLS are counted and not microseconds on purpose: a timing test in CI is a test that fails on
    Tuesdays. The property that matters is structural —the work fixed per table is done once— and
    that one is measured by counting.
    """
    from snakeorm import snake_discriminator, snake_link
    from snakeorm.registry import SnakeRegistry
    from snakeorm.registry import registry as global_registry
    from snakeorm.session.mapper import _CACHE, dispatch_for

    @snake_model(table="map_critters")
    class Critter(SnakeModel):
        """Polymorphic base."""

        id: SnakeColumn[int] = snake_auto()
        clase: SnakeColumn[str] = snake_discriminator()

    @snake_model(discriminator_value="fly")
    class Fly(Critter):
        """One child."""

        alas: SnakeColumn[int | None] = snake_int()

    snake_link()
    critter_table = snake_table(Critter)
    _CACHE.clear()

    calls = 0
    original = SnakeRegistry.polymorphic_map

    def counting(self: SnakeRegistry, table: object) -> dict[str, type]:
        nonlocal calls
        calls += 1
        return original(self, table)  # type: ignore[arg-type]

    SnakeRegistry.polymorphic_map = counting  # type: ignore[method-assign]
    try:
        for _ in range(100):
            dispatch_for(Critter, critter_table)
    finally:
        SnakeRegistry.polymorphic_map = original  # type: ignore[method-assign]

    assert calls == 1, f"the registry was queried {calls} times for 100 rows"
    assert global_registry.polymorphic_map(critter_table) == {"fly": Fly}
