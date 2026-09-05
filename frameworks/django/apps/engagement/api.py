"""Thin JSON API for the engagement domain (comments, reactions, visits): DRF (`@api_view`) over `shared`.

Thin views: they parse the request, call the use case with flat parameters and serialize with the
shared DTOs (data) or map the `Failure` to its status (error). Zero queries, zero `commit`. The
SnakeORM session is hung on `request.snake_session` by `SnakeSessionMiddleware`. DRF handles CSRF
(`@csrf_exempt` is gone) and `@extend_schema` documents each operation at `/api/docs`
(drf-spectacular).

Since Django routes a URL to ONE view, each `posts/{id}/{comments,reactions,visits}` route (GET list
+ POST create) is handled by a single view that dispatches on the method.

THE EXPORT IS THE ONE ROUTE HERE THAT IS NOT A DRF VIEW, and that is not tidiness: it answers with a
`StreamingHttpResponse` whose body is produced after the view has returned, so it opens a session of
its own instead of borrowing the request's. `apps/exports.py` argues the whole of it.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


from django.http import HttpRequest, StreamingHttpResponse

from apps import exports, wire
from apps.session import snake_session
from apps.engagement import usecases, viewmodels
from shared.dto.engagement_dto import (
    comment_dict,
    reaction_dict,
    visit_dict,
    visit_tally_dict,
)
from shared.usecases.result import FAILURE_STATUS


_session = snake_session


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def post_comments(request: Request, post_id: int) -> Response:
    """GET: the post's comments. POST `{author_id, body}`: adds one (201, 400 if the body is empty)."""
    session = _session(request)
    if request.method == "POST":
        payload = wire.json_object(request)
        result = usecases.add_comment(
            session,
            post_id,
            wire.integer(payload["author_id"]),
            wire.text(payload["body"]),
        )
        if isinstance(result, usecases.Failure):
            return Response(
                {"detail": result.reason}, status=FAILURE_STATUS[result.reason]
            )
        return Response(comment_dict(result), status=201)
    comments = usecases.comments_of_post(session, post_id)
    return Response([comment_dict(c) for c in comments])


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def post_reactions(request: Request, post_id: int) -> Response:
    """GET: the post's reactions. POST `{user_id, kind}`: records one (201, 400 if the kind is missing)."""
    session = _session(request)
    if request.method == "POST":
        payload = wire.json_object(request)
        result = usecases.add_reaction(
            session,
            post_id,
            wire.integer(payload["user_id"]),
            wire.text(payload["kind"]),
        )
        if isinstance(result, usecases.Failure):
            return Response(
                {"detail": result.reason}, status=FAILURE_STATUS[result.reason]
            )
        return Response(reaction_dict(result), status=201)
    reactions = usecases.reactions_of_post(session, post_id)
    return Response([reaction_dict(r) for r in reactions])


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def post_visits(request: Request, post_id: int) -> Response:
    """GET: the post's visits. POST `{ip, user_agent?}`: records one and reports the new counter.

    201 with the visit AND `visit_count`, which is the number the TRIGGER wrote — not one the
    handler added up. 404 if the post is not there.
    """
    session = _session(request)
    if request.method == "POST":
        payload = wire.json_object(request)
        result = usecases.record_visit(
            session,
            post_id,
            wire.text(payload["ip"]),
            wire.optional_text(payload.get("user_agent")),
        )
        if isinstance(result, usecases.Failure):
            return Response(
                {"detail": result.reason}, status=FAILURE_STATUS[result.reason]
            )
        return Response(visit_tally_dict(result), status=201)
    visits = usecases.visits_of_post(session, post_id)
    return Response([visit_dict(v) for v in visits])


def visits_export(request: HttpRequest) -> StreamingHttpResponse:
    """The whole traffic log as a STREAMED CSV: one statement, narrow rows, flat memory.

    Not a page and not a JSON document: a file. It sits on the API surface because this domain has
    no SSR section of its own, and the same route answers in the three demos — the asynchronous one
    serves it with `async for` over the same query.

    THE SESSION IS NOT THE REQUEST'S, and `apps/exports.py` argues why at length: the middleware
    closes `request.snake_session` the moment this function returns, and a streamed body is produced
    afterwards. `csv_download` opens one that lives exactly as long as the download.

    IT IS A PLAIN DJANGO VIEW AND NOT AN `@api_view`, and the parameter type is the tell. DRF wraps
    the request and answers `query_params`; this route is registered bare, so what arrives is an
    `HttpRequest` and the query string is `request.GET`. Annotating it `Request` would have type
    checked and raised `AttributeError` on the first download — a wrapper that is not there cannot
    be asked for what it would have provided.

    `?post=` narrows the QUERY and not the writer.
    """
    raw = request.GET.get("post")
    post_id = int(raw) if raw is not None and raw.strip().isdigit() else None
    return exports.csv_download(
        lambda session: viewmodels.visits_export(session, post_id=post_id)
    )
