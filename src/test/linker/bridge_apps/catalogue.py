"""Catalogue app: Post, Tag and ITS OWN Tagging bridge, crossed by the CLASS.

The bridge is declared FIRST, which is the only arrangement in which a class can be handed to
`through=` at all — the class has to exist when `Post`'s body runs. Its own relations point back
with STRING annotations, which the linker resolves later with `get_type_hints`, so the cycle costs
nothing. That is why the string form of `through=` stays the normal way to write this: most bridges
are declared after the model that crosses them, and then there is no class to hand over.
"""

from __future__ import annotations

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToMany,
    SnakeToOne,
    snake_int,
    snake_model,
    snake_str,
    snake_to_many_through,
    snake_to_one,
)
from test.linker.bridge_apps import bridge_registry


@snake_model(table="br_cat_tags", registry=bridge_registry)
class Tag(SnakeModel):
    """A catalogue tag."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="br_cat_taggings", registry=bridge_registry)
class Tagging(SnakeModel):
    """The catalogue bridge. Its class name is shared with the archive app's."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    post_id: SnakeColumn[int] = snake_int()
    tag_id: SnakeColumn[int] = snake_int()
    post: SnakeToOne["Post"] = snake_to_one(post_id)
    tag: SnakeToOne[Tag] = snake_to_one(tag_id)


@snake_model(table="br_cat_posts", registry=bridge_registry)
class Post(SnakeModel):
    """Crosses to `Tag` through the bridge above, handed over as the CLASS and not by name."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    title: SnakeColumn[str] = snake_str()
    tags: SnakeToMany[Tag] = snake_to_many_through(
        through=Tagging, via="post", to="tag"
    )
