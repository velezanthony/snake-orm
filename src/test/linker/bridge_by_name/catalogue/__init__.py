"""The catalogue app: its own Tag, Post and Tagging, crossed by NAME."""

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
from test.linker.bridge_by_name import bridge_registry


@snake_model(table="bn_cat_tags", registry=bridge_registry)
class Tag(SnakeModel):
    """This app's tag."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    label: SnakeColumn[str] = snake_str()


@snake_model(table="bn_cat_posts", registry=bridge_registry)
class Post(SnakeModel):
    """Crosses to Tag through a bridge declared BELOW, so the name is the only way to say it."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    tags: SnakeToMany[Tag] = snake_to_many_through(
        through="Tagging", via="post", to="tag"
    )


@snake_model(table="bn_cat_taggings", registry=bridge_registry)
class Tagging(SnakeModel):
    """This app's bridge. Its class name is shared with the other app's."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    post_id: SnakeColumn[int] = snake_int()
    tag_id: SnakeColumn[int] = snake_int()
    post: SnakeToOne[Post] = snake_to_one(post_id)
    tag: SnakeToOne[Tag] = snake_to_one(tag_id)
