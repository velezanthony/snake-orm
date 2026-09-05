"""auth domain — SELECTORS: reads of a user's API tokens and login sessions.

Every framework re-exports them from `apps/auth/selectors.py`.

Each read comes in TWO pieces: the FRAGMENT builds a `SnakeQuery` and does not run it, the EXECUTOR
takes a session and runs it. Only the executor has a colour, so the SQL is written once and both the
synchronous demos and the asynchronous one in `shared/aio/` run the very same query.
"""

from __future__ import annotations

from snakeorm import SnakeQuery, SnakeSession

from shared.models import ApiToken, LoginSession


def tokens_of(user_id: int) -> SnakeQuery[ApiToken]:
    """FRAGMENT: every API token of a user, newest first."""
    return (
        SnakeQuery(ApiToken)
        .filter(ApiToken.user_id == user_id)
        .order_by(ApiToken.created_at.desc())
    )


def token_by_id(token_id: int) -> SnakeQuery[ApiToken]:
    """FRAGMENT: ONE token, if it is there.

    A read, so it lives here, even though the only caller that wants it is the service that REVOKES
    it: revoking is "find the token, mark it", and the asynchronous twin has to find it with exactly
    this `WHERE` rather than with a second one that merely looks alike today.
    """
    return SnakeQuery(ApiToken).filter(ApiToken.id == token_id)


def login_sessions_of(user_id: int) -> SnakeQuery[LoginSession]:
    """FRAGMENT: a user's login sessions, most recent first."""
    return (
        SnakeQuery(LoginSession)
        .filter(LoginSession.user_id == user_id)
        .order_by(LoginSession.created_at.desc())
    )


def tokens_of_user(session: SnakeSession, user_id: int) -> list[ApiToken]:
    """Every API token of a user, newest first."""
    return session.all(tokens_of(user_id))


def active_of(user_id: int) -> SnakeQuery[ApiToken]:
    """FRAGMENT: a user's tokens that have not been REVOKED, neither executed nor ordered.

    IT DOES NOT LOOK AT `expires_at`, and the two callers above it used to say it did. That is a
    known gap rather than a subtlety — `auth_usecases.active_tokens` documents it in full — and it
    is named here as well because this is the line somebody would read to check.

    More can be stacked on top —order, limit, count— and the type survives all the way to the end.
    It was duplicated in `catalog` with a different ordering; now the query is a single one and what
    changes is whatever each caller adds to it.
    """
    return SnakeQuery(ApiToken).filter(
        ApiToken.user_id == user_id,
        ApiToken.revoked == False,  # noqa: E712
    )


def active_tokens(session: SnakeSession, user_id: int) -> list[ApiToken]:
    """Only a user's LIVE tokens (not revoked), newest first."""
    return session.all(active_of(user_id).order_by(ApiToken.created_at.desc()))


def sessions_of_user(session: SnakeSession, user_id: int) -> list[LoginSession]:
    """A user's login sessions, most recent first."""
    return session.all(login_sessions_of(user_id))
