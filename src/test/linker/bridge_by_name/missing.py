"""A model whose `through=` names a bridge no module declares. Its own registry, linked on demand.

At MODULE level for the reason the collision fixtures write down: the compiler resolves annotations
with `get_type_hints`, which reads the module globals, so a class defined inside a function would
fail to resolve and the test would go red for the wrong reason.
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

orphan_registry = SnakeRegistry()


@snake_model(table="bn_orphan_tags", registry=orphan_registry)
class OrphanTag(SnakeModel):
    """The far end of a bridge that does not exist."""

    id: SnakeColumn[int] = snake_int(primary_key=True)


@snake_model(table="bn_orphan_posts", registry=orphan_registry)
class OrphanPost(SnakeModel):
    """Crosses through a name this module cannot see."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    tags: SnakeToMany[OrphanTag] = snake_to_many_through(
        through="Nope", via="post", to="tag"
    )
