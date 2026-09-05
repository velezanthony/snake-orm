"""A model whose `through=` names a bridge nobody declared. Its own registry, never linked here.

At MODULE level and not inside the test function, for the reason `collision_apps` writes down: the
compiler resolves annotations with `get_type_hints`, which reads the module globals, so a class
defined in a function would fail to resolve and the test would go red for the wrong reason.
"""

from __future__ import annotations

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToMany,
    snake_int,
    snake_model,
    snake_to_many_through,
)
from snakeorm.registry import SnakeRegistry

broken_registry = SnakeRegistry()


@snake_model(table="br_orphan_tags", registry=broken_registry)
class OrphanTag(SnakeModel):
    """The far end of a bridge that does not exist."""

    id: SnakeColumn[int] = snake_int(primary_key=True)


@snake_model(table="br_orphan_posts", registry=broken_registry)
class OrphanPost(SnakeModel):
    """Crosses through a name nobody registered."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    tags: SnakeToMany[OrphanTag] = snake_to_many_through(
        through="Nope", via="post", to="tag"
    )
