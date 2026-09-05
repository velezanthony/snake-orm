"""JSON API of the engagement domain (comments, reactions, visits): thin endpoints over `shared`.

Every endpoint parses the request, calls the use case with flat parameters and translates the result
into JSON (data -> DTO, `Failure` -> `abort(status)`). The ORM session is opened by the blog's
`before_app_request` hook in `g.session`.

THE EXPORT IS THE ONE ROUTE THAT DOES NOT GIVE THE SESSION BACK, and it says so where it is written:
a streamed body is produced after the request context is gone, so the stream takes ownership.

**The blueprint here is `engagement-api` and the pages next door are `engagement`.** Two
blueprints cannot share a `url_for` name, and this one held the plain one for as long as the
domain had no pages to collide with it — the same story `inventory`, `billing` and `taxonomy` each
went through. The convention they settled is applied here: a plain name is the pages, the `-api`
suffix is the JSON.
"""

from __future__ import annotations

from flask import abort, g, jsonify, request
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from apps import wire
from apps.engagement import usecases, viewmodels
from apps.exports import csv_response
from shared.dto.engagement_dto import (
    comment_dict,
    reaction_dict,
    visit_dict,
    visit_tally_dict,
)
from shared.usecases.result import FAILURE_STATUS

engagement = Blueprint(
    "engagement-api",
    __name__,
    url_prefix="/api/engagement",
    description="Engagement: comments, reactions and visits",
)


@engagement.get("/posts/<int:post_id>/comments")
def comments_of_post(post_id: int) -> ResponseReturnValue:
    """The comments of a post."""
    return jsonify(
        [comment_dict(c) for c in usecases.comments_of_post(g.session, post_id)]
    )


@engagement.get("/posts/<int:post_id>/reactions")
def reactions_of_post(post_id: int) -> ResponseReturnValue:
    """The reactions of a post."""
    return jsonify(
        [reaction_dict(r) for r in usecases.reactions_of_post(g.session, post_id)]
    )


@engagement.get("/posts/<int:post_id>/visits")
def visits_of_post(post_id: int) -> ResponseReturnValue:
    """The recorded visits of a post."""
    return jsonify([visit_dict(v) for v in usecases.visits_of_post(g.session, post_id)])


@engagement.post("/posts/<int:post_id>/comments")
def add_comment(post_id: int) -> ResponseReturnValue:
    """Add a comment to a post. 400 if the body comes in empty, 404 if the post does not exist."""
    payload = wire.json_object(request)
    result = usecases.add_comment(
        g.session,
        post_id,
        wire.integer(payload.get("author_id")),
        wire.text(payload.get("body")),
    )
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(comment_dict(result)), 201


@engagement.post("/posts/<int:post_id>/reactions")
def add_reaction(post_id: int) -> ResponseReturnValue:
    """Add a reaction to a post. 404 if the post does not exist."""
    payload = wire.json_object(request)
    result = usecases.add_reaction(
        g.session,
        post_id,
        wire.integer(payload.get("user_id")),
        wire.text(payload.get("kind")),
    )
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(reaction_dict(result)), 201


@engagement.post("/posts/<int:post_id>/visits")
def record_visit(post_id: int) -> ResponseReturnValue:
    """Record a visit and report the counter the TRIGGER wrote. 404 if the post is not there.

    `visit_count` is read back off the database and not added up here: the number is kept by the
    engine, so the only honest way to answer it is to ask the row that changed.
    """
    payload = wire.json_object(request)
    result = usecases.record_visit(
        g.session,
        post_id,
        wire.text(payload.get("ip")),
        wire.optional_text(payload.get("user_agent")),
    )
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(visit_tally_dict(result)), 201


@engagement.get("/visits/export")
def visits_export() -> ResponseReturnValue:
    """The whole traffic log as a STREAMED CSV: one statement, narrow rows, flat memory.

    `csv_response` is the last statement of this function on purpose — it TAKES the session with it,
    popping `g.session` so the teardown hook has nothing to close and the stream owns the connection
    until the download ends. Nothing may touch the session afterwards.

    `?post=` narrows the QUERY and not the writer: filtering while writing would read every visit of
    every post in order to throw most of them away, on the one route whose subject is not doing that.
    """
    export = viewmodels.visits_export(
        g.session, post_id=request.args.get("post", default=None, type=int)
    )
    return csv_response(export)
