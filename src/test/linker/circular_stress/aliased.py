"""The block spelled the OTHER way round, and the name bound under an ALIAS.

Two spellings in one file on purpose: recognising only the bare `TYPE_CHECKING` would reject a file
that is correct, and reading `alias.name` instead of `alias.asname` would look for a name the module
never bound. Both are fail-in-the-open shapes — they do not raise, they just do not find.
"""

from __future__ import annotations

import typing

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToMany,
    snake_int,
    snake_model,
    snake_to_many,
)
from test.linker.circular_stress import stress_registry

if typing.TYPE_CHECKING:
    from test.linker.circular_stress.aliased_target import Target as Aliased


@snake_model(table="stress_aliased", registry=stress_registry)
class Aliaser(SnakeModel):
    """Its to-many names the class by the alias the import bound, not by its own name."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    targets: SnakeToMany[Aliased] = snake_to_many("owner")
