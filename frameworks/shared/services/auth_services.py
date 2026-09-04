"""auth domain — SERVICES: issue/revoke API tokens and open login sessions.

`created_at` is set by the DB (server default `NOW`), so it is not passed in. Every framework
re-exports them from `apps/auth/services.py`.
"""

from __future__ import annotations


from snakeorm import SnakeUtc, SnakeSession

from shared.models import ApiToken, LoginSession
from shared.selectors.auth_selectors import token_by_id


def issue_token(
    session: SnakeSession,
    user_id: int,
    token: str,
    expires_at: SnakeUtc,
    label: str | None = None,
) -> ApiToken:
    """Issues an API token for a user, with its expiry."""
    return session.add(
        ApiToken(token=token, label=label, user_id=user_id, expires_at=expires_at)
    )


def revoke_token(session: SnakeSession, token_id: int) -> bool:
    """Revokes a token (marks it `revoked`). `False` if it does not exist."""
    token = session.first(token_by_id(token_id))
    if token is None:
        return False
    token.revoked = True
    session.update(token)
    return True


def open_login_session(
    session: SnakeSession, user_id: int, ip: str, user_agent: str | None = None
) -> LoginSession:
    """Records a login session for a user."""
    return session.add(
        LoginSession(
            user_id=user_id,
            ip=ip,
            user_agent=user_agent,
            last_seen_at=SnakeUtc.now(),
        )
    )
