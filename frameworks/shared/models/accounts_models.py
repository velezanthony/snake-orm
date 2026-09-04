"""ACCOUNTS domain: identity. `User` (login) and `Role`+`UserRole` (the N—N of permissions).

`User` is the root of the graph: almost every domain references it. Its INVERSE relationships live
here even when the child is in another file: the annotation is a string ref (`SnakeToMany["Post"]`)
and `snake_link()` resolves it against the global registry after every domain is imported. That is
exactly what the linker is for: zero cross imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeResult,
    SnakeServerDefault,
    SnakeToMany,
    SnakeToOne,
    SnakeUtc,
    snake_auto,
    snake_datetimetz,
    snake_int,
    snake_model,
    snake_result,
    snake_str,
    snake_to_many,
    snake_to_many_through,
    snake_to_one,
)

if TYPE_CHECKING:
    # For the TYPE-CHECKER only: names from other domains used in the INVERSE relationships. At
    # runtime they are NOT imported (they would be circular) — the linker gets them through the
    # globals injection in `models/__init__.py`. TYPE_CHECKING solves the static side; the injection
    # solves the runtime side.
    from shared.models.auth_models import ApiToken, LoginSession
    from shared.models.billing_models import Subscription
    from shared.models.blog_models import Blog, Post
    from shared.models.engagement_models import Comment
    from shared.models.orders_models import Order


@snake_model(table="users")
class User(SnakeModel):
    """User: login (unique username/email), owner of blogs and author of posts/comments."""

    id: SnakeColumn[int] = snake_auto()
    username: SnakeColumn[str] = snake_str(unique=True)
    email: SnakeColumn[str] = snake_str(unique=True)
    password_hash: SnakeColumn[str] = snake_str()
    # The DB sets the signup date (RETURNING): "now" is fine for a user, the seeder does not spread it.
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )
    roles: SnakeToMany["Role"] = snake_to_many_through(
        through="UserRole", via="user", to="role"
    )
    api_tokens: SnakeToMany["ApiToken"] = snake_to_many("user")
    sessions: SnakeToMany["LoginSession"] = snake_to_many("user")
    blogs: SnakeToMany["Blog"] = snake_to_many("owner")
    posts: SnakeToMany["Post"] = snake_to_many("author")
    comments: SnakeToMany["Comment"] = snake_to_many("author")
    subscriptions: SnakeToMany["Subscription"] = snake_to_many("user")
    # The inverse of `Order.customer`. It is a TO-MANY, so it adds no foreign key here and no
    # migration: the column lives on the child, and this side is navigation.
    orders: SnakeToMany["Order"] = snake_to_many("customer")


@snake_model(table="roles")
class Role(SnakeModel):
    """A role (admin, author, reader). `User` ↔ `Role` is N—N through the `UserRole` bridge."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(unique=True)
    users: SnakeToMany[User] = snake_to_many_through(
        through="UserRole", via="role", to="user"
    )


@snake_model(table="user_roles")
class UserRole(SnakeModel):
    """The BRIDGE of the `User` ↔ `Role` N—N: an ordinary model with its two FKs (no magic table)."""

    id: SnakeColumn[int] = snake_auto()
    user_id: SnakeColumn[int] = snake_int(index=True)
    role_id: SnakeColumn[int] = snake_int(index=True)
    user: SnakeToOne[User] = snake_to_one(user_id)
    role: SnakeToOne[Role] = snake_to_one(role_id)


@snake_result
class UserStats(SnakeResult[User]):
    """Typed container for `session.annotate()`: the user + its aggregates (posts, comments)."""

    user: User
    post_count: int
    comment_count: int


# The domain's models, in local dependency order for the DDL.
ACCOUNTS_MODELS = (User, Role, UserRole)
