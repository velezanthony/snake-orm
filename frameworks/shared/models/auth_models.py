"""AUTH domain: a `User`'s access. `ApiToken` (1—N of tokens) and `LoginSession` (1—N of sessions).

Both hang off `User` (accounts domain) by FK; the global `snake_link()` resolves it. They give
surface for state queries: live vs expired tokens, recent sessions, and so on.
"""

from __future__ import annotations


from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeServerDefault,
    SnakeToOne,
    SnakeUtc,
    snake_auto,
    snake_column,
    snake_datetimetz,
    snake_int,
    snake_model,
    snake_str,
    snake_to_one,
)

from shared.models.accounts_models import User


@snake_model(table="api_tokens")
class ApiToken(SnakeModel):
    """API token of a `User` (1—N). `expires_at` is spread by the seeder (some live, some expired)."""

    id: SnakeColumn[int] = snake_auto()
    token: SnakeColumn[str] = snake_str(unique=True)
    label: SnakeColumn[str | None] = snake_str()  # nullable because of the annotation
    revoked: SnakeColumn[bool] = snake_column(default=False)
    user_id: SnakeColumn[int] = snake_int(index=True)
    user: SnakeToOne[User] = snake_to_one(user_id)
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )
    expires_at: SnakeColumn[SnakeUtc] = snake_datetimetz()


@snake_model(table="login_sessions")
class LoginSession(SnakeModel):
    """Login session of a `User` (1—N). `last_seen_at` is spread by the seeder over the history."""

    id: SnakeColumn[int] = snake_auto()
    user_id: SnakeColumn[int] = snake_int(index=True)
    user: SnakeToOne[User] = snake_to_one(user_id)
    ip: SnakeColumn[str] = snake_str()
    user_agent: SnakeColumn[str | None] = (
        snake_str()
    )  # nullable because of the annotation
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )
    last_seen_at: SnakeColumn[SnakeUtc] = snake_datetimetz()


# The domain's models, in local dependency order for the DDL.
AUTH_MODELS = (ApiToken, LoginSession)
