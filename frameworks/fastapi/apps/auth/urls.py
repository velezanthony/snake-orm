"""Router of the auth domain (API tokens and login sessions): a thin JSON API over the use cases.

Every endpoint parses the request (Pydantic), calls the use case with flat parameters and translates
the result into JSON (data -> DTO, `Failure` -> HTTPException). Zero queries, zero `commit` here.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from apps.auth import usecases
from apps.auth.usecases import Failure
from apps.deps import SessionDep, http_error
from shared.dto.auth_dto import login_session_dict, token_dict

router = APIRouter(prefix="/api/auth", tags=["auth"])


class TokenIn(BaseModel):
    """Body for issuing an API token (the label is optional)."""

    label: str | None = None


@router.get("/users/{user_id}/tokens")
async def tokens_of_user(user_id: int, session: SessionDep) -> list[dict[str, object]]:
    """Every API token of a user."""
    return [token_dict(t) for t in await usecases.tokens_of_user(session, user_id)]


@router.get("/users/{user_id}/tokens/active")
async def active_tokens(user_id: int, session: SessionDep) -> list[dict[str, object]]:
    """The active API tokens (neither revoked nor expired) of a user."""
    return [token_dict(t) for t in await usecases.active_tokens(session, user_id)]


@router.get("/users/{user_id}/sessions")
async def sessions_of_user(
    user_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """The login sessions of a user."""
    return [
        login_session_dict(s) for s in await usecases.sessions_of_user(session, user_id)
    ]


@router.post("/users/{user_id}/tokens", status_code=201)
async def issue_token(
    user_id: int, payload: TokenIn, session: SessionDep
) -> dict[str, object]:
    """Issue an API token for a user, with an optional label."""
    return token_dict(await usecases.issue_token(session, user_id, payload.label))


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(token_id: int, session: SessionDep) -> None:
    """Revoke an API token. 404 if the token does not exist."""
    result = await usecases.revoke_token(session, token_id)
    if isinstance(result, Failure):
        raise http_error(result)
