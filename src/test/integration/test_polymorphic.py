"""POLYMORPHIC inheritance end to end: one table, several classes, and the row knows which it is.

It is the ORM's second kind of inheritance and it is worth not confusing it with the one already
there:

- **Concrete**: each class its own table, duplicated columns. `Dog` and `Cat` are two tables.
- **Polymorphic** (this one): ONE table and a column that says what each row is. `session.all(Animal)`
  returns dogs and cats hydrated with their REAL class, and `session.all(Dog)` filters by itself.

It is tested against in-memory SQLite because polymorphism has nothing engine-specific about it —it
is a column and a `WHERE`— and this way the test runs without a server. What does get really tested
is the complete cycle: DDL, insert, read and filtering, because the four pieces live in different
places of the code (compiler, linker, `plan_insert`, `_instantiate`) and the only thing that proves
they fit together is making them work together.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SQLiteDialect,
    SQLiteDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_auto,
    snake_discriminator,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
    snake_table,
)
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.migration import emit_create_table
from snakeorm.registry import SnakeRegistry
from snakeorm.registry import registry as _REG

# The hierarchy lives in the GLOBAL registry on purpose: `SnakeQuery` resolves it from there, so an
# isolated registry would leave the query tests testing something else. The names are prefixed
# (`poli_`) so they do not clash with those of the other files.


@snake_model(table="poli_animales")
class Animal(SnakeModel):
    """The base of the hierarchy: it owns the table and it is the one that sees every row."""

    id: SnakeColumn[int] = snake_auto()
    kind: SnakeColumn[str] = snake_discriminator()
    name: SnakeColumn[str] = snake_str()


@snake_model(discriminator_value="dog")
class Dog(Animal):
    """One child: it contributes `raza` to the shared table."""

    raza: SnakeColumn[str | None] = snake_str()


@snake_model(discriminator_value="cat")
class Cat(Animal):
    """Another child: it contributes `vidas`, which does not exist on the dog rows."""

    vidas: SnakeColumn[int | None] = snake_int()


snake_link()


@pytest.fixture
def session() -> Iterator[SnakeSession]:
    """An in-memory database with the hierarchy table already created and populated."""
    driver = SQLiteDriver.connect(":memory:")
    table = _REG.table_of(Animal)
    assert table is not None
    driver.execute(emit_create_table(table, SQLiteDialect()), ())
    driver.commit()
    try:
        yield SnakeSession(driver, SQLiteDialect())
    finally:
        driver.close()


def test_the_shared_table_carries_every_subclass_column() -> None:
    """The BASE table carries the columns of all its children, or the DDL would come out incomplete.

    The base is decorated BEFORE the children exist, so only the linker can resolve this —just like
    relationships—. Attempting it in the decorator would depend on import order, which is exactly
    the bug that already cost an FK pointing at the wrong table.
    """
    columns = [column.name for column in snake_table(Animal, _REG).columns]

    assert set(columns) == {"id", "kind", "name", "raza", "vidas"}


def test_the_children_do_not_declare_a_table_of_their_own() -> None:
    """The three classes point at the SAME physical table. That is the whole point of this inheritance."""
    names = {snake_table(model, _REG).name for model in (Animal, Dog, Cat)}

    assert names == {"poli_animales"}


def test_the_discriminator_is_written_without_anyone_remembering_it(
    session: SnakeSession,
) -> None:
    """When inserting a `Dog`, `kind` fills itself in: the CLASS sets it, not whoever writes the code.

    If it depended on the user remembering `Dog(kind="dog", ...)`, one slip would store a row
    that is later read as a generic `Animal`, without a single error along the way.
    """
    session.add(Dog(name="Toby", raza="mestizo"))
    session.commit()

    row = session.first(SnakeQuery(Animal))

    assert row is not None and row.kind == "dog"


def test_reading_the_base_hydrates_each_row_as_its_real_class(
    session: SnakeSession,
) -> None:
    """THE test: querying the base returns dogs and cats, each with ITS class and ITS fields.

    It is what concrete inheritance cannot give without a hand-written `UNION`, and the reason
    someone chooses this kind of inheritance.
    """
    session.add(Dog(name="Toby", raza="mestizo"))
    session.add(Cat(name="Pelusa", vidas=9))
    session.commit()

    animals = sorted(session.all(SnakeQuery(Animal)), key=lambda a: a.name)

    assert [type(a).__name__ for a in animals] == ["Cat", "Dog"]
    assert isinstance(animals[0], Cat) and animals[0].vidas == 9
    assert isinstance(animals[1], Dog) and animals[1].raza == "mestizo"


def test_a_sibling_column_does_not_leak_into_the_other_class(
    session: SnakeSession,
) -> None:
    """A `Dog` does NOT keep the `vidas` column that came with the base row.

    The `Animal` row includes the columns of all the siblings. Writing them anyway would leave a
    ghost attribute on the dog, with no descriptor behind it: invisible until someone printed it or
    compared it, which is the worst possible moment to find out.
    """
    session.add(Dog(name="Toby", raza="mestizo"))
    session.commit()

    dog = session.first(SnakeQuery(Animal))

    assert isinstance(dog, Dog)
    # The STORAGE, not `hasattr`. A ghost has no descriptor by definition, so `hasattr` answers
    # False whether the value was written or not: it cannot see the thing this test is named after.
    # The mapper writes into `__snake_<attr>`, and that is where the ghost would be sitting.
    assert "__snake_vidas" not in vars(dog), "the sibling's column does not travel"
    assert not hasattr(dog, "vidas")


def test_querying_a_child_filters_by_its_discriminator(session: SnakeSession) -> None:
    """`session.all(Dog)` sees only dogs. Without the filter it would return cats hydrated as dogs.

    The filter is seeded in the query constructor, so EVERY path inherits it —`all`, `first`,
    `count`, `exists`, the bulk deletes— without any of them having to remember.
    """
    session.add(Dog(name="Toby", raza="mestizo"))
    session.add(Cat(name="Pelusa", vidas=9))
    session.commit()

    dogs = session.all(SnakeQuery(Dog))

    assert [p.name for p in dogs] == ["Toby"]
    assert session.count(SnakeQuery(Dog)) == 1, "the filter reaches the aggregate too"


def test_the_base_query_still_sees_the_whole_hierarchy(session: SnakeSession) -> None:
    """The control for the previous test: the BASE carries no filter, and that is not an oversight.

    Querying `Animal` has to see the whole hierarchy; if it filtered by anything, this inheritance
    would have no advantage over the concrete one.
    """
    session.add(Dog(name="Toby", raza="mestizo"))
    session.add(Cat(name="Pelusa", vidas=9))
    session.commit()

    assert session.count(SnakeQuery(Animal)) == 2


def test_a_child_column_that_forbids_null_is_rejected_at_declaration_time() -> None:
    """An own NOT NULL column would make inserting the siblings impossible, and it is said at declaration time.

    The table is one: the `vidas` column of `Cat` also exists on the `Dog` rows, where there is
    nothing to put. Finding out when inserting the first dog would mean finding out in production.
    """
    other = SnakeRegistry()

    @snake_model(table="poli_base2", registry=other)
    class Base(SnakeModel):
        """base"""

        id: SnakeColumn[int] = snake_auto()
        kind: SnakeColumn[str] = snake_discriminator()

    with pytest.raises(SnakeModelDefinitionError, match="have to accept NULL"):

        @snake_model(discriminator_value="hija", registry=other)
        class Hija(Base):
            """child with a mandatory column"""

            obligatoria: SnakeColumn[int] = snake_int()


def test_a_child_without_a_polymorphic_base_is_rejected() -> None:
    """`discriminator_value` without a base that opens a hierarchy means nothing, and it is said."""
    other = SnakeRegistry()

    with pytest.raises(
        SnakeModelDefinitionError,
        match="none of its base classes opens a polymorphic hierarchy",
    ):

        @snake_model(discriminator_value="huerfana", registry=other)
        class Huerfana(SnakeModel):
            """without a polymorphic base"""

            id: SnakeColumn[int] = snake_auto()


def test_the_discriminator_is_not_a_constructor_argument() -> None:
    """The discriminator does NOT enter the `__init__`, and mypy and pyright have to see that too.

    It is the reason it is declared with `snake_discriminator()` and not with a `discriminator="kind"`
    in the decorator: only a field specifier can carry the `init: Literal[False]` that the checkers
    read. With the parameter, both would demand `Dog(kind="dog", ...)` while the runtime fills it
    in by itself — a type that lies, which this project considers worse than having no type at all.

    What is checked here is the RUNTIME side; the checkers' side is covered by `test/typing/`, and
    the two agreeing is the whole thesis.
    """
    dog = Dog(name="Toby", raza="mestizo")

    assert dog.kind == "dog", "the constructor fills it in, unasked"
    with pytest.raises(TypeError, match=r"unexpected arguments: \['kind'\]"):
        Dog(name="Toby", raza="mestizo", kind="cat")  # type: ignore[call-arg]


def test_the_discriminator_gets_an_index_without_being_asked() -> None:
    """The column indexes itself, because EVERY query on a subclass carries it in its `WHERE`.

    A default you have to remember to switch on is a badly chosen default: without an index, every
    read of `Dog` walks the whole hierarchy.
    """
    indexes = snake_table(Animal, _REG).indexes

    assert any(index.columns == ("kind",) for index in indexes)


def test_iterate_hydrates_the_same_classes_as_all(session: SnakeSession) -> None:
    """`iterate()` decides the concrete class exactly as `all()` does. Same rows, same types.

    `_instantiate` says of itself that it is "the ONLY point where the concrete class of a
    polymorphic hierarchy gets decided", and that `all`/`first`/`get`/`include` inherit it without
    noticing. `iterate` is not on that list — it called `hydrate` straight — so streaming the same
    query gave back `Animal` objects where `all()` gave `Dog` and `Cat`. Worse than the wrong class:
    hydrating a row as the base leaves the SIBLINGS' columns on the instance, so a dog came out
    carrying a cat's attributes.

    Both sessions had it, which is what makes the pair below the assertion and not just `all()`: a
    streamed read is the one people reach for over big tables, and it was the one quietly answering
    with a different type.
    """
    session.add(Dog(name="Laika", raza="galgo"))
    session.add(Cat(name="Milu", vidas=9))
    session.commit()

    query = SnakeQuery(Animal).order_by(Animal.id)
    from_all = [type(animal).__name__ for animal in session.all(query)]
    from_iterate = [type(animal).__name__ for animal in session.iterate(query)]

    assert from_iterate == from_all, (
        f"all() hydrated {from_all} and iterate() hydrated {from_iterate}: the same rows came "
        f"back as different classes depending on how they were read."
    )
    assert from_all == ["Dog", "Cat"], f"the hierarchy itself is broken: {from_all}"
