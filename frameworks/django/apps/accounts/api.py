"""Thin JSON API for the accounts domain (roles): DRF (`@api_view`) over the `shared` use cases.

Every view parses the request (`request.data` for POST, path params from the route), calls the use
case with plain parameters and serializes with the shared DTOs (data) or maps the `Failure` to its
status (error). Zero queries, zero `commit`. The SnakeORM session is hung on `request.snake_session`
by `SnakeSessionMiddleware`. DRF handles CSRF (no more `@csrf_exempt` needed) and `@extend_schema`
documents each operation at `/api/docs` (drf-spectacular).

Unlike FastAPI/Flask, Django routes a URL to ONE view regardless of the method; that is why the
routes serving GET and POST at once (e.g. `/accounts/roles`) are handled by a single view that
dispatches on `request.method`, preserving the same URL surface as the other frameworks.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


from apps import wire
from apps.session import snake_session
from apps.accounts import usecases
from shared.dto.accounts_dto import role_dict
from shared.usecases.result import FAILURE_STATUS


_session = snake_session


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def roles(request: Request) -> Response:
    """GET: every role in the system. POST `{name}`: creates a role (400 if the name comes empty)."""
    session = _session(request)
    if request.method == "POST":
        body = wire.json_object(request)
        result = usecases.create_role(session, wire.text(body["name"]))
        if isinstance(result, usecases.Failure):
            return Response(
                {"detail": result.reason}, status=FAILURE_STATUS[result.reason]
            )
        return Response(role_dict(result), status=201)
    return Response([role_dict(r) for r in usecases.list_roles(session)])


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def user_roles(request: Request, user_id: int) -> Response:
    """GET: a user's roles. POST `{role_id}`: assigns one to them (404 if the role does not exist)."""
    session = _session(request)
    if request.method == "POST":
        role_id = wire.integer(wire.json_object(request)["role_id"])
        result = usecases.assign_role(session, user_id, role_id)
        if isinstance(result, usecases.Failure):
            return Response(
                {"detail": result.reason}, status=FAILURE_STATUS[result.reason]
            )
        return Response({"user_id": user_id, "role_id": role_id}, status=201)
    roles_of_user = usecases.roles_of_user(session, user_id)
    return Response([role_dict(r) for r in roles_of_user])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["DELETE"])
def revoke_role(request: Request, user_id: int, role_id: int) -> Response:
    """Removes a role from a user. 404 if that assignment did not exist."""
    result = usecases.revoke_role(_session(request), user_id, role_id)
    if isinstance(result, usecases.Failure):
        return Response({"detail": result.reason}, status=FAILURE_STATUS[result.reason])
    return Response(status=204)
