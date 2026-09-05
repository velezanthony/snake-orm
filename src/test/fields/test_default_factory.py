"""The split between default (a literal, for the DDL) and default_factory (a callable, Python only).

`default` feeds the DDL (a literal DEFAULT) and therefore accepts ONLY literals; `default_factory`
is a callable that runs while the object is being built and NEVER reaches the DDL. Declaring both
is a contradiction, and handing a callable to `default` is the classic mistake that drops a function
into the CREATE TABLE: both are rejected loudly. The generated __init__ calls the factory when the
field is missing.
"""

from __future__ import annotations

import pytest

from snakeorm.decorators import snake_model
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.fields import SnakeColumn, snake_column, snake_int, snake_str

from snakeorm.model import SnakeModel


def test_default_and_default_factory_together_raise() -> None:
    """Declaring `default` and `default_factory` at once contradicts itself: it raises."""
    with pytest.raises(
        SnakeModelDefinitionError,
        match="Do not declare `default` and `default_factory` at the same",
    ):
        snake_column(default=5, default_factory=lambda: 5)


def test_callable_default_raises_pointing_to_factory() -> None:
    """A callable in `default` (the classic datetime.now) is rejected, and points at the factory."""
    with pytest.raises(SnakeModelDefinitionError, match="default_factory"):
        snake_column(default=list)


def test_init_uses_default_factory_per_instance() -> None:
    """__init__ runs the factory when the field is missing, ONCE per instance: a fresh value."""
    counter = {"n": 0}

    def factory() -> int:
        counter["n"] += 1
        return counter["n"]

    @snake_model
    class Widget(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        serial: SnakeColumn[int] = snake_int(default_factory=factory)

    first = Widget(id=1)
    second = Widget(id=2)
    assert first.serial == 1
    assert second.serial == 2  # the factory runs again, the value is not shared


def test_default_factory_gives_a_fresh_object_each_time() -> None:
    """The factory yields a brand new object per instance: it kills the shared mutable default."""

    @snake_model
    class Bag(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        items: SnakeColumn[list[str]] = snake_column(default_factory=list)

    a = Bag(id=1)
    b = Bag(id=2)
    a.items.append("x")
    assert b.items == []


def test_explicit_value_overrides_factory() -> None:
    """If the argument is passed, the factory is never called: the explicit value rules."""

    @snake_model
    class Node(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        tag: SnakeColumn[str] = snake_str(default_factory=lambda: "auto")

    assert Node(id=1, tag="manual").tag == "manual"


def test_literal_default_still_feeds_metadata() -> None:
    """A literal `default` is still valid and is kept as such, because the DDL needs it."""
    descriptor = snake_column(default=7)
    assert descriptor.default == 7
    assert descriptor.has_default is True
    assert descriptor.has_default_factory is False
