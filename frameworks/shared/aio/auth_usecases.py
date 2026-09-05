"""auth domain (API tokens and login sessions), asked of an `AsyncSession`.

The twin of `shared/usecases/auth_usecases.py`: same names, same parameters, same answers. The
queries come from `shared/selectors/auth_selectors.py` untouched — a `SnakeQuery` has no colour, so
the `revoked == False` that decides which tokens are live is one object on both paths, and a live
token cannot come to mean two different things depending on which session asked.

The token SECRET is generated here as it is there, with the same `secrets.token_urlsafe(32)` and the
same thirty-day lifetime. That is the one duplication in this file worth naming out loud: it is a
security decision, and two copies of a security decision is how one of them quietly gets weaker. The
constant is imported from the synchronous module rather than retyped, so the number lives once.
"""

from __future__ import annotations

import secrets

from snakeorm import SnakeUtc, AsyncSession

from shared.models import ApiToken, LoginSession
from shared.selectors.auth_selectors import (
    active_of,
    login_sessions_of,
    token_by_id,
    tokens_of,
)
from shared.usecases.auth_usecases import _TOKEN_TTL
from shared.usecases.result import Failure


async def tokens_of_user(session: AsyncSession, user_id: int) -> list[ApiToken]:
    """Every token of a user (active and revoked), newest first."""
    return await session.all(tokens_of(user_id))


async def active_tokens(session: AsyncSession, user_id: int) -> list[ApiToken]:
    """A user's live tokens (not revoked), newest first."""
    return await session.all(active_of(user_id).order_by(ApiToken.created_at.desc()))


async def sessions_of_user(session: AsyncSession, user_id: int) -> list[LoginSession]:
    """A user's login sessions, most recent first."""
    return await session.all(login_sessions_of(user_id))


async def issue_token(
    session: AsyncSession, user_id: int, label: str | None = None
) -> ApiToken:
    """Issues a new token (generated secret, expiring in 30 days) and commits it."""
    now = SnakeUtc.now()
    token = await session.add(
        ApiToken(
            token=secrets.token_urlsafe(32),
            label=label,
            user_id=user_id,
            expires_at=now + _TOKEN_TTL,
        )
    )
    await session.commit()
    return token


async def revoke_token(session: AsyncSession, token_id: int) -> None | Failure:
    """Revokes a token; `not_found` if it does not exist."""
    token = await session.first(token_by_id(token_id))
    if token is None:
        return Failure("not_found")
    token.revoked = True
    await session.update(token)
    await session.commit()
    return None
