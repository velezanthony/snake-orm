"""JSON API of the taxonomy domain (tag groups and tags): thin endpoints over `shared`.

Every endpoint parses the request, calls the use case with flat parameters and translates the result
into JSON (data -> DTO, `Failure` -> `abort(status)`). `tag_post` is IDEMPOTENT and says which of the
two things happened: the pair comes back as `{post_id, tag_id}` with 201 when this call created the
link and 200 when the post already carried the tag. The ORM session is opened by the blog's
`before_app_request` hook in `g.session`.
"""

from __future__ import annotations

from flask import abort, g, jsonify, request
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from apps import wire
from apps.taxonomy import usecases
from shared.dto.blog_dto import post_dict
from shared.dto.taxonomy_dto import group_dict, tag_dict, tag_tree_dict
from shared.usecases.result import FAILURE_STATUS

taxonomy = Blueprint(
    # `-api` because the plain `taxonomy` belongs to the PAGES in `urls.py`, the way
    # `blog`/`blog-api`, `inventory`/`inventory-api` and `billing`/`billing-api` already split. This
    # blueprint held the plain name while the domain had no pages, which worked exactly until it had
    # some: two blueprints cannot share one `url_for` name.
    "taxonomy-api",
    __name__,
    url_prefix="/api/taxonomy",
    description="Taxonomy: tag groups and tags",
)


@taxonomy.get("/groups")
def list_groups() -> ResponseReturnValue:
    """Every tag group."""
    return jsonify([group_dict(g_) for g_ in usecases.list_groups(g.session)])


@taxonomy.get("/tags")
def list_tags() -> ResponseReturnValue:
    """Every tag."""
    return jsonify([tag_dict(t) for t in usecases.list_tags(g.session)])


@taxonomy.get("/posts/<int:post_id>/tags")
def tags_of_post(post_id: int) -> ResponseReturnValue:
    """The tags of a post (through the PostTag bridge table)."""
    return jsonify([tag_dict(t) for t in usecases.tags_of_post(g.session, post_id)])


@taxonomy.post("/tags")
def create_tag() -> ResponseReturnValue:
    """Create a tag inside a group, optionally UNDER another. 400 on an empty name, 404 on no group."""
    payload = wire.json_object(request)
    result = usecases.create_tag(
        g.session,
        wire.text(payload.get("name")),
        wire.integer(payload.get("group_id")),
        wire.optional_integer(payload.get("parent_id")),
    )
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(tag_dict(result)), 201


@taxonomy.get("/posts")
def filter_posts() -> ResponseReturnValue:
    """Posts by tag. `?tags=1,2` carries ALL of them; adding `&without=3` subtracts that one.

    One route and two questions, because that is one screen: the tick boxes that narrow and the one
    that excludes. `without` is what decides which — with it the first tag is the base and the
    excluded one is taken off it; without it the tags are intersected and fewer than two is a 400,
    since "the posts of one tag" is a different question with an operation of its own.
    """
    raw = request.args.get("tags", "")
    tag_ids = [int(piece) for piece in raw.split(",") if piece.strip()]
    without = request.args.get("without")
    if without is not None:
        if not tag_ids:
            abort(FAILURE_STATUS["missing_fields"])
        posts = usecases.posts_with_tag_but_not(g.session, tag_ids[0], int(without))
        return jsonify([post_dict(post) for post in posts])
    result = usecases.posts_with_every_tag(g.session, tag_ids)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify([post_dict(post) for post in result])


@taxonomy.post("/posts/<int:post_id>/tags")
def tag_post(post_id: int) -> ResponseReturnValue:
    """Tag a post. 201 when this call created the link, 200 when it was already there."""
    payload = wire.json_object(request)
    tag_id = wire.integer(payload.get("tag_id"))
    post_tag, created = usecases.tag_post(g.session, post_id, tag_id)
    return (
        jsonify({"post_id": post_tag.post_id, "tag_id": post_tag.tag_id}),
        201 if created else 200,
    )


@taxonomy.delete("/posts/<int:post_id>/tags/<int:tag_id>")
def untag_post(post_id: int, tag_id: int) -> ResponseReturnValue:
    """Take a tag away from a post. 404 if that relation did not exist."""
    result = usecases.untag_post(g.session, post_id, tag_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return "", 204


@taxonomy.get("/tags/<int:tag_id>/tree")
def tag_tree(tag_id: int) -> ResponseReturnValue:
    """Where a tag sits in the taxonomy and what hangs off it. 404 if the tag is not there.

    TWO statements whatever the depth: one recursion climbs to the root and the other descends to
    the leaves. The JSON half of the page at `/taxonomy/tree/<id>`, over the same two use cases.
    """
    breadcrumb = usecases.tag_breadcrumb(g.session, tag_id)
    if isinstance(breadcrumb, usecases.Failure):
        abort(FAILURE_STATUS[breadcrumb.reason])
    branch = usecases.tag_descendants(g.session, tag_id)
    return jsonify(tag_tree_dict(breadcrumb, branch))
