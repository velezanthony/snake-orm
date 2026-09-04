"""A many-to-many with a MISSPELLED hop, in its own registry.

It lives in an actual module because the compiler resolves the annotations with `get_type_hints`,
which looks at the MODULE globals: classes defined inside a function would not resolve their forward
reference and the test would fail for a reason other than the one it claims to measure.

And in its own registry so as not to leave the global one with a model that does not link.
"""

from __future__ import annotations

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToMany,
    SnakeToOne,
    snake_auto,
    snake_int,
    snake_model,
    snake_to_many_through,
    snake_to_one,
)
from snakeorm.registry import SnakeRegistry

reg = SnakeRegistry()
"""Registry isolated for this scenario."""


@snake_model(table="mal_a", registry=reg)
class A(SnakeModel):
    """End with the misspelled `via`: 'no_existe' is not a relation of the bridge."""

    id: SnakeColumn[int] = snake_auto()
    bes: SnakeToMany[B] = snake_to_many_through(
        through="Bridge", via="no_existe", to="b"
    )


@snake_model(table="mal_b", registry=reg)
class B(SnakeModel):
    """The other end."""

    id: SnakeColumn[int] = snake_auto()


@snake_model(table="mal_bridge", registry=reg)
class Bridge(SnakeModel):
    """The bridge, with its two relations correctly in place: `a` and `b`."""

    id: SnakeColumn[int] = snake_auto()
    a_id: SnakeColumn[int] = snake_int()
    b_id: SnakeColumn[int] = snake_int()
    a: SnakeToOne[A] = snake_to_one(a_id)
    b: SnakeToOne[B] = snake_to_one(b_id)
