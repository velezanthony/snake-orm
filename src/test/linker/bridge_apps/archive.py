"""Archive app: another Tagging. Same class name, another table, another concept."""

from __future__ import annotations

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToOne,
    snake_int,
    snake_model,
    snake_str,
    snake_to_one,
)
from test.linker.bridge_apps import bridge_registry


@snake_model(table="br_arc_tags", registry=bridge_registry)
class Tag(SnakeModel):
    """An archive tag: nothing to do with the catalogue one."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    label: SnakeColumn[str] = snake_str()


@snake_model(table="br_arc_posts", registry=bridge_registry)
class Post(SnakeModel):
    """An archive post."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    title: SnakeColumn[str] = snake_str()


@snake_model(table="br_arc_taggings", registry=bridge_registry)
class Tagging(SnakeModel):
    """The archive bridge. It registers LAST, so it owns the name "Tagging" in the by-name index."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    post_id: SnakeColumn[int] = snake_int()
    tag_id: SnakeColumn[int] = snake_int()
    post: SnakeToOne[Post] = snake_to_one(post_id)
    tag: SnakeToOne[Tag] = snake_to_one(tag_id)
