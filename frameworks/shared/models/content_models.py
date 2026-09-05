"""CONTENT domain: pieces hanging off a `Post`. `PostRevision` (the edit history) and `Attachment`
(an attached file). Both 1—N from `Post` (blog domain).
"""

from __future__ import annotations


from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeToOne,
    SnakeUtc,
    snake_auto,
    snake_datetimetz,
    snake_int,
    snake_model,
    snake_str,
    snake_to_one,
)

from shared.models.blog_models import Post


@snake_model(table="post_revisions")
class PostRevision(SnakeModel):
    """A previous version of a `Post`'s body (1—N). `edited_at` is spread by the seeder."""

    id: SnakeColumn[int] = snake_auto()
    post_id: SnakeColumn[int] = snake_int(index=True)
    post: SnakeToOne[Post] = snake_to_one(post_id)
    body: SnakeColumn[str] = snake_str()
    edited_at: SnakeColumn[SnakeUtc] = snake_datetimetz()


@snake_model(table="attachments")
class Attachment(SnakeModel):
    """A file attached to a `Post` (1—N): name, URL and size in bytes."""

    id: SnakeColumn[int] = snake_auto()
    post_id: SnakeColumn[int] = snake_int(index=True)
    post: SnakeToOne[Post] = snake_to_one(post_id)
    filename: SnakeColumn[str] = snake_str()
    url: SnakeColumn[str] = snake_str()
    size_bytes: SnakeColumn[int] = snake_int()


# The domain's models, in local dependency order for the DDL.
CONTENT_MODELS = (PostRevision, Attachment)
