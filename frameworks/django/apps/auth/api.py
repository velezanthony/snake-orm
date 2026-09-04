"""Thin JSON API for the auth domain (tokens and login sessions): DRF (`@api_view`) over `shared`.

Thin views: they parse the request, call the use case with flat parameters and serialize with the
shared DTOs (data) or map the `Failure` to its status (error). Zero queries, zero `commit`. The
SnakeORM session is hung on `request.snake_session` by `SnakeSessionMiddleware`. DRF handles CSRF
(`@csrf_exempt` is gone) and `@extend_schema` documents each operation at `/api/docs`
(drf-spectacular).

Since Django routes a URL to ONE view, the `users/{id}/tokens` route (GET list + POST issue) is
handled by a single view that dispatches on the method.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


from apps import wire
from apps.session import snake_session
from apps.auth import usecases
from shared.dto.auth_dto import login_session_dict, token_dict
from shared.usecases.result import FAILURE_STATUS


_session = snake_session


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def user_tokens(request: Request, user_id: int) -> Response:
    """GET: every token of the user. POST `{label?}`: issues a new token (201)."""
    session = _session(request)
    if request.method == "POST":
        label = wire.optional_text(wire.json_object(request).get("label"))
        token = usecases.issue_token(session, user_id, label)
        return Response(token_dict(token), status=201)
    return Response([token_dict(t) for t in usecases.tokens_of_user(session, user_id)])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def active_tokens(request: Request, user_id: int) -> Response:
    """Only the user's valid tokens (not revoked and not expired)."""
    tokens = usecases.active_tokens(_session(request), user_id)
    return Response([token_dict(t) for t in tokens])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def sessions_of_user(request: Request, user_id: int) -> Response:
    """The user's login sessions."""
    sessions = usecases.sessions_of_user(_session(request), user_id)
    return Response([login_session_dict(s) for s in sessions])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["DELETE"])
def revoke_token(request: Request, token_id: int) -> Response:
    """Revokes a token. 404 if it does not exist."""
    result = usecases.revoke_token(_session(request), token_id)
    if isinstance(result, usecases.Failure):
        return Response({"detail": result.reason}, status=FAILURE_STATUS[result.reason])
    return Response(status=204)
