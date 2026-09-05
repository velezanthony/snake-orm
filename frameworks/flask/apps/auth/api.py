"""JSON API of the auth domain (API tokens and login sessions): thin endpoints over `shared`.

Every endpoint parses the request, calls the use case with flat parameters and translates the result
into JSON (data -> DTO, `Failure` -> `abort(status)`). The token's secret value is NEVER serialized
(the DTO redacts it). The ORM session is opened by the blog's `before_app_request` hook in
`g.session`.
"""

from __future__ import annotations

from flask import abort, g, jsonify, request
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from apps import wire
from apps.auth import usecases
from shared.dto.auth_dto import login_session_dict, token_dict
from shared.usecases.result import FAILURE_STATUS

auth = Blueprint(
    "auth-api",
    __name__,
    url_prefix="/api/auth",
    description="Auth: API tokens and login sessions",
)


@auth.get("/users/<int:user_id>/tokens")
def tokens_of_user(user_id: int) -> ResponseReturnValue:
    """Every API token of a user."""
    return jsonify([token_dict(t) for t in usecases.tokens_of_user(g.session, user_id)])


@auth.get("/users/<int:user_id>/tokens/active")
def active_tokens(user_id: int) -> ResponseReturnValue:
    """Only the active (not revoked) tokens of a user."""
    return jsonify([token_dict(t) for t in usecases.active_tokens(g.session, user_id)])


@auth.get("/users/<int:user_id>/sessions")
def sessions_of_user(user_id: int) -> ResponseReturnValue:
    """The login sessions of a user."""
    return jsonify(
        [login_session_dict(s) for s in usecases.sessions_of_user(g.session, user_id)]
    )


@auth.post("/users/<int:user_id>/tokens")
def issue_token(user_id: int) -> ResponseReturnValue:
    """Issue an API token for a user. The `label` is optional."""
    payload = wire.json_object(request)
    token = usecases.issue_token(
        g.session, user_id, wire.optional_text(payload.get("label"))
    )
    return jsonify(token_dict(token)), 201


@auth.delete("/tokens/<int:token_id>")
def revoke_token(token_id: int) -> ResponseReturnValue:
    """Revoke a token. 404 if it does not exist."""
    result = usecases.revoke_token(g.session, token_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return "", 204
