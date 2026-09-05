"""Thin JSON API for the content domain (post revisions and attachments): DRF (`@api_view`) over `shared`.

Thin views: they parse the request, call the use case with flat parameters and serialize with the
shared DTOs (data) or map the `Failure` to its status (error). Zero queries, zero `commit`. The
SnakeORM session is hung on `request.snake_session` by `SnakeSessionMiddleware`. DRF handles CSRF
(`@csrf_exempt` is gone) and `@extend_schema` documents each operation at `/api/docs`
(drf-spectacular).

Since Django routes a URL to ONE view, the `posts/{id}/revisions` and `posts/{id}/attachments`
routes (GET list + POST create) are handled by a single view that dispatches on the method.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


from apps import wire
from apps.session import snake_session
from apps.content import usecases
from shared.dto.content_dto import (
    attachment_dict,
    revision_dict,
    revision_stub_dict,
)
from shared.usecases.result import FAILURE_STATUS


_session = snake_session


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def post_revisions(request: Request, post_id: int) -> Response:
    """GET: the post's revisions. POST `{body}`: adds a revision (201, 400 if the body is empty)."""
    session = _session(request)
    if request.method == "POST":
        payload = wire.json_object(request)
        result = usecases.add_revision(session, post_id, wire.text(payload["body"]))
        if isinstance(result, usecases.Failure):
            return Response(
                {"detail": result.reason}, status=FAILURE_STATUS[result.reason]
            )
        return Response(revision_dict(result), status=201)
    revisions = usecases.revisions_of_post(session, post_id)
    return Response([revision_dict(r) for r in revisions])


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def post_attachments(request: Request, post_id: int) -> Response:
    """GET: the post's attachments. POST `{filename, url, size_bytes}`: attaches a file (201)."""
    session = _session(request)
    if request.method == "POST":
        payload = wire.json_object(request)
        result = usecases.attach_file(
            session,
            post_id,
            wire.text(payload["filename"]),
            wire.text(payload["url"]),
            wire.integer(payload["size_bytes"]),
        )
        if isinstance(result, usecases.Failure):
            return Response(
                {"detail": result.reason}, status=FAILURE_STATUS[result.reason]
            )
        return Response(attachment_dict(result), status=201)
    attachments = usecases.attachments_of_post(session, post_id)
    return Response([attachment_dict(a) for a in attachments])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["DELETE"])
def remove_attachment(request: Request, attachment_id: int) -> Response:
    """Removes an attachment. 404 if it does not exist."""
    result = usecases.remove_attachment(_session(request), attachment_id)
    if isinstance(result, usecases.Failure):
        return Response({"detail": result.reason}, status=FAILURE_STATUS[result.reason])
    return Response(status=204)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def post_history(request: Request, post_id: int) -> Response:
    """WHEN a post was edited, newest first — the history, without the histories.

    The sibling of `posts/{id}/revisions` and a different question from it. That one answers what the
    post said and carries every body; this one answers how often and when, and the query leaves the
    body behind — on a post edited two hundred times the difference is two hundred copies of an
    article that nothing here prints.
    """
    revisions = usecases.revision_timeline(_session(request), post_id)
    return Response([revision_stub_dict(revision) for revision in revisions])
