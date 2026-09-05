"""JSON API of the content domain (a post's revisions and attachments): thin endpoints over `shared`.

Every endpoint parses the request, calls the use case with flat parameters and translates the result
into JSON (data -> DTO, `Failure` -> `abort(status)`). The ORM session is opened by the blog's
`before_app_request` hook in `g.session`.

**The blueprint here is `content-api` and the pages next door are `content`.** Two
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
from apps.content import usecases
from shared.dto.content_dto import (
    attachment_dict,
    revision_dict,
    revision_stub_dict,
)
from shared.usecases.result import FAILURE_STATUS

content = Blueprint(
    "content-api",
    __name__,
    url_prefix="/api/content",
    description="Content: post revisions and attachments",
)


@content.get("/posts/<int:post_id>/revisions")
def revisions_of_post(post_id: int) -> ResponseReturnValue:
    """The revisions (edit history) of a post."""
    return jsonify(
        [revision_dict(r) for r in usecases.revisions_of_post(g.session, post_id)]
    )


@content.get("/posts/<int:post_id>/attachments")
def attachments_of_post(post_id: int) -> ResponseReturnValue:
    """The attachments of a post."""
    return jsonify(
        [attachment_dict(a) for a in usecases.attachments_of_post(g.session, post_id)]
    )


@content.post("/posts/<int:post_id>/revisions")
def add_revision(post_id: int) -> ResponseReturnValue:
    """Add a revision to a post. 400 if the body comes in empty, 404 if the post does not exist."""
    payload = wire.json_object(request)
    result = usecases.add_revision(g.session, post_id, wire.text(payload.get("body")))
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(revision_dict(result)), 201


@content.post("/posts/<int:post_id>/attachments")
def attach_file(post_id: int) -> ResponseReturnValue:
    """Attach a file to a post. 400 if fields are missing, 404 if the post does not exist."""
    payload = wire.json_object(request)
    result = usecases.attach_file(
        g.session,
        post_id,
        wire.text(payload.get("filename")),
        wire.text(payload.get("url")),
        wire.integer(payload.get("size_bytes")),
    )
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(attachment_dict(result)), 201


@content.delete("/attachments/<int:attachment_id>")
def remove_attachment(attachment_id: int) -> ResponseReturnValue:
    """Delete an attachment. 404 if it does not exist."""
    result = usecases.remove_attachment(g.session, attachment_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return "", 204


@content.get("/posts/<int:post_id>/history")
def revision_timeline(post_id: int) -> ResponseReturnValue:
    """WHEN a post was edited, newest first — the history, without the histories.

    The sibling of `/revisions` and a different question: that one carries every body, this one
    carries none. The rows arrive from a `defer()`, so the DTO beside it cannot start naming `body`
    by accident — it would raise rather than print an empty string.
    """
    return jsonify(
        [
            revision_stub_dict(revision)
            for revision in usecases.revision_timeline(g.session, post_id)
        ]
    )
