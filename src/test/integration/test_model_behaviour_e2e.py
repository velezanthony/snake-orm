"""Polymorphic inheritance and signals, over the THREE engines.

Two model-level features that were exercised on one engine and are not engine-neutral in the way
that sounds obvious:

- **Inheritance** is one table plus a discriminator, so the hydration reads a value the DATABASE
  returned and picks a Python class from it. What each engine hands back for a `str` column is
  exactly the kind of thing that differs, and the wrong class is not an error — it is an object of
  the wrong type walking off into the caller.
- **Signals** are pure Python and fire around the session, so they SHOULD be identical everywhere.
  That is a claim, and a claim about all three that is only ever run on one is the shape this whole
  round is about. It costs one parametrise to stop being a claim.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_auto,
    snake_discriminator,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.core.signals import SnakeSignal, disconnect_all, snake_on
from snakeorm.linker import snake_link
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@snake_model(table="mbe_animals")
class Animal(SnakeModel):
    """The base: it owns the table and it is the one that sees every row."""

    id: SnakeColumn[int] = snake_auto()
    kind: SnakeColumn[str] = snake_discriminator()
    name: SnakeColumn[str] = snake_str(max_length=40)


@snake_model(discriminator_value="dog")
class Dog(Animal):
    """One child: it contributes a column the cat rows do not have."""

    breed: SnakeColumn[str | None] = snake_str(max_length=40)


@snake_model(discriminator_value="cat")
class Cat(Animal):
    """The other child."""

    lives: SnakeColumn[int | None] = snake_int()


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with one dog and one cat in the shared table.

    `snake_link()` first, and it is not ceremony: linking is what MERGES the subclasses' columns
    into the base table. Without it the DDL is emitted from `Animal` alone and the insert answers
    `no column named breed` — the two-phase discipline of the compiler, seen from the outside.
    """
    snake_link()
    with three_sessions([Animal]) as sessions:
        for session in sessions.values():
            session.add(Dog(name="Laika", breed="husky"))
            session.add(Cat(name="Tama", lives=9))
            session.commit()
        yield sessions


@pytest.mark.parametrize("engine", _ENGINES)
def test_reading_the_base_hydrates_each_row_as_its_own_class(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """One query over the base, two Python classes back. The discriminator decides, not the caller.

    Asserted by TYPE and not by a field: a hydration that built every row as `Animal` would still
    answer the right names, and the caller would only find out when it touched `breed`.
    """
    session = engines[engine]

    rows = session.all(SnakeQuery(Animal).order_by(Animal.id.asc()))

    assert [type(row).__name__ for row in rows] == ["Dog", "Cat"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_each_child_carries_only_its_own_column(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The columns of the sibling are NULL on this row, and the class is what says which are which."""
    session = engines[engine]

    rows = session.all(SnakeQuery(Animal).order_by(Animal.id.asc()))
    dog, cat = rows[0], rows[1]

    assert isinstance(dog, Dog) and dog.breed == "husky"
    assert isinstance(cat, Cat) and cat.lives == 9


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_four_signals_fire_in_order_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Signals are Python and fire around the session, so the ORDER must not depend on the engine.

    `PRE_` before the write and `POST_` after it — a handler that saw them the other way round
    would be reading a row that does not exist yet, or acting on one already gone.
    """
    session = engines[engine]
    seen: list[str] = []

    try:
        for signal in SnakeSignal:

            @snake_on(Cat, signal)
            def note(row: Cat, signal: SnakeSignal = signal) -> None:
                """Writes down which signal fired."""
                seen.append(signal.value)

        written = session.add(Cat(name="Momo", lives=7))
        session.delete(written)
        session.commit()
    finally:
        disconnect_all(Cat)

    assert seen == ["pre_save", "post_save", "pre_delete", "post_delete"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_refusing_handler_stops_the_write_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """A `PRE_SAVE` that raises must stop the INSERT, and the row must not be there afterwards.

    Reading the exception alone would pass on a session that raised after writing — so what is
    checked is the table.
    """
    session = engines[engine]
    before = session.count(SnakeQuery(Animal))

    try:

        @snake_on(Cat, SnakeSignal.PRE_SAVE)
        def refuse(row: Cat) -> None:
            """Refuses the write."""
            raise ValueError("not this one")

        with pytest.raises(ValueError, match="not this one"):
            session.add(Cat(name="Nope", lives=1))
    finally:
        disconnect_all(Cat)
    session.rollback()

    assert session.count(SnakeQuery(Animal)) == before
