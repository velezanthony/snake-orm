"""A to-many that declares its child OPTIONAL (`SnakeToMany[Comment | None]`), in its own registry.

It lives in an actual module because the two models reference each other: the parent names the
child and the child names the parent back, so one of the two annotations is always a forward
reference. `get_type_hints` resolves those against the MODULE globals, and classes defined inside a
test function are not there — the test would fail with a `NameError` instead of with the thing it
claims to measure.

And in its own registry so as not to leave the global one carrying a model that does not link.

`snake_link()` is deliberately NOT called here: importing the module must succeed, because the
refusal being measured belongs to link time and the test is what triggers it.
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
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.registry import SnakeRegistry

reg = SnakeRegistry()
"""Registry isolated for this scenario."""


@snake_model(table="optional_children_posts", registry=reg)
class Post(SnakeModel):
    """The parent, whose collection wrongly claims it may be `None` instead of empty."""

    id: SnakeColumn[int] = snake_auto()
    comments: SnakeToMany[Comment | None] = snake_to_many("post")


@snake_model(table="optional_children_comments", registry=reg)
class Comment(SnakeModel):
    """The child, holding the foreign key the to-many above reverses."""

    id: SnakeColumn[int] = snake_auto()
    body: SnakeColumn[str] = snake_str()
    post_id: SnakeColumn[int] = snake_int()
    post: SnakeToOne[Post] = snake_to_one(post_id)
