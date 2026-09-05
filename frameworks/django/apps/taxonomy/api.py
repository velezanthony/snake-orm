"""Thin JSON API for the taxonomy domain (groups, tags and post tagging): DRF (`@api_view`) over `shared`.

Thin views: they parse the request, call the use case with flat parameters and serialize with the
shared DTOs (data) or map the `Failure` to its status (error). Zero queries, zero `commit`. The
SnakeORM session is hung on `request.snake_session` by `SnakeSessionMiddleware`. DRF handles CSRF
(`@csrf_exempt` is gone) and `@extend_schema` documents each operation at `/api/docs`
(drf-spectacular).

Since Django routes a URL to ONE view, the `tags` and `posts/{id}/tags` routes (GET list + POST
create/tag) are handled by a single view that dispatches on the method. `tag_post` does not return
`Failure`.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


from apps import wire
from apps.session import snake_session
from apps.taxonomy import usecases
from shared.dto.blog_dto import post_dict
from shared.dto.taxonomy_dto import group_dict, tag_dict, tag_tree_dict
from shared.usecases.result import FAILURE_STATUS


_session = snake_session


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def list_groups(request: Request) -> Response:
    """Every tag group."""
    groups = usecases.list_groups(_session(request))
    return Response([group_dict(g) for g in groups])


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def tags(request: Request) -> Response:
    """GET: every tag. POST `{name, group_id, parent_id?}`: creates one (201, 400 on an empty name).

    `parent_id` is optional because a root is the ordinary case: it is what puts the new tag
    somewhere in the TREE instead of at the top of it.
    """
    session = _session(request)
    if request.method == "POST":
        body = wire.json_object(request)
        result = usecases.create_tag(
            session,
            wire.text(body["name"]),
            wire.integer(body["group_id"]),
            wire.optional_integer(body.get("parent_id")),
        )
        if isinstance(result, usecases.Failure):
            return Response(
                {"detail": result.reason}, status=FAILURE_STATUS[result.reason]
            )
        return Response(tag_dict(result), status=201)
    return Response([tag_dict(t) for t in usecases.list_tags(session)])


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(
    methods=["POST"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT
)
@api_view(["GET", "POST"])
def post_tags(request: Request, post_id: int) -> Response:
    """GET: the post's tags. POST `{tag_id}`: tags the post (201 created, 200 already tagged)."""
    session = _session(request)
    if request.method == "POST":
        tag_id = wire.integer(wire.json_object(request)["tag_id"])
        link, created = usecases.tag_post(session, post_id, tag_id)
        return Response(
            {"post_id": link.post_id, "tag_id": link.tag_id},
            status=201 if created else 200,
        )
    return Response([tag_dict(t) for t in usecases.tags_of_post(session, post_id)])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def filter_posts(request: Request) -> Response:
    """Posts by tag. `?tags=1,2` carries ALL of them; adding `&without=3` subtracts that one.

    One route and two questions, because that is one screen: the tick boxes that narrow and the one
    that excludes. `without` is what decides which — with it the first tag is the base and the
    excluded one is taken off it; without it the tags are intersected and fewer than two is a 400,
    since "the posts of one tag" is a different question with an operation of its own.
    """
    session = _session(request)
    raw = request.query_params.get("tags", "")
    tag_ids = [int(piece) for piece in raw.split(",") if piece.strip()]
    without = request.query_params.get("without")
    if without is not None:
        if not tag_ids:
            return Response({"detail": "missing_fields"}, status=400)
        posts = usecases.posts_with_tag_but_not(session, tag_ids[0], int(without))
        return Response([post_dict(post) for post in posts])
    result = usecases.posts_with_every_tag(session, tag_ids)
    if isinstance(result, usecases.Failure):
        return Response({"detail": result.reason}, status=FAILURE_STATUS[result.reason])
    return Response([post_dict(post) for post in result])


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["DELETE"])
def untag_post(request: Request, post_id: int, tag_id: int) -> Response:
    """Removes a tag from a post. 404 if that relation did not exist."""
    result = usecases.untag_post(_session(request), post_id, tag_id)
    if isinstance(result, usecases.Failure):
        return Response({"detail": result.reason}, status=FAILURE_STATUS[result.reason])
    return Response(status=204)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def tag_tree(request: Request, tag_id: int) -> Response:
    """Where a tag sits in the taxonomy and what hangs off it. 404 if the tag is not there.

    TWO statements whatever the depth: one recursion climbs to the root and the other descends to
    the leaves. The same pair the page draws — this is the BFF half of `/taxonomy/tree/<id>/`, not a
    second implementation of it.
    """
    session = _session(request)
    breadcrumb = usecases.tag_breadcrumb(session, tag_id)
    if isinstance(breadcrumb, usecases.Failure):
        return Response(
            {"detail": breadcrumb.reason}, status=FAILURE_STATUS[breadcrumb.reason]
        )
    branch = usecases.tag_descendants(session, tag_id)
    return Response(tag_tree_dict(breadcrumb, branch))
