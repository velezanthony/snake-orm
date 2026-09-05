"""ENGAGEMENT domain: interaction with a `Post`. `Comment` (a `User` comments), `Visit` (a page view,
the VOLUME table) and `Reaction` (like/love/…).

`Visit` is the big table (millions of rows at the high scales): the one that gives room for pagination
and traffic aggregates. Every date is spread by the seeder over the history (`datetime` columns).
"""

from __future__ import annotations


from snakeorm import (
    SnakeTriggerEvent,
    SnakeTriggerTiming,
    snake_trigger,
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

from shared.models.accounts_models import User
from shared.models.blog_models import Post


@snake_model(table="comments")
class Comment(SnakeModel):
    """A comment from a `User` on a `Post`. `created_at` is spread by the seeder over the history."""

    id: SnakeColumn[int] = snake_auto()
    body: SnakeColumn[str] = snake_str()
    post_id: SnakeColumn[int] = snake_int(index=True)
    post: SnakeToOne[Post] = snake_to_one(post_id)
    author_id: SnakeColumn[int] = snake_int(index=True)
    author: SnakeToOne[User] = snake_to_one(author_id)
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz()


@snake_model(table="visits")
class Visit(SnakeModel):
    """A visit (page view) to a `Post`. The VOLUME table: pagination and traffic aggregates."""

    id: SnakeColumn[int] = snake_auto()
    post_id: SnakeColumn[int] = snake_int(index=True)
    post: SnakeToOne[Post] = snake_to_one(post_id)
    ip: SnakeColumn[str] = snake_str()
    user_agent: SnakeColumn[str | None] = (
        snake_str()
    )  # nullable because of the annotation
    visited_at: SnakeColumn[SnakeUtc] = snake_datetimetz()


@snake_model(table="reactions")
class Reaction(SnakeModel):
    """A reaction (like/love/wow) from a `User` to a `Post`. `kind` stores the type."""

    id: SnakeColumn[int] = snake_auto()
    kind: SnakeColumn[str] = snake_str()
    post_id: SnakeColumn[int] = snake_int(index=True)
    post: SnakeToOne[Post] = snake_to_one(post_id)
    user_id: SnakeColumn[int] = snake_int(index=True)
    user: SnakeToOne[User] = snake_to_one(user_id)
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz()


# The domain's models, in local dependency order for the DDL.
ENGAGEMENT_MODELS = (Comment, Visit, Reaction)


# The one trigger in the demos, and it is here because this is the domain that needs one.
#
# `Post.visit_count` is denormalised. Keeping it from the ORM would mean every writer of a `Visit`
# remembering to bump it — including the seeder, a `session.raw`, and anything that reaches this
# database without going through Python at all. The rule this ORM gives for choosing a trigger is
# exactly that: if the invariant has to hold ALWAYS, it belongs in the engine.
#
# The BODY is written once. It is inline SQL, which is what MySQL and SQLite take; on PostgreSQL,
# where a trigger calls a function instead, the dialect wraps it and emits the call. Writing it three
# times to say one thing is what that translation exists to avoid.
visit_counter = snake_trigger(
    name="tg_bump_visit_count",
    table="visits",
    timing=SnakeTriggerTiming.AFTER,
    events=(SnakeTriggerEvent.INSERT,),
    body="UPDATE posts SET visit_count = visit_count + 1 WHERE id = NEW.post_id;",
)
