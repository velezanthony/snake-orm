"""Router of the content domain (post revisions and attachments): a thin JSON API over the use cases.

Every endpoint parses the request (Pydantic), calls the use case with flat parameters and translates
the result into JSON (data -> DTO, `Failure` -> HTTPException). Zero queries, zero `commit` here.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from apps.content import usecases
from apps.content.usecases import Failure
from apps.deps import SessionDep, http_error
from shared.dto.content_dto import (
    attachment_dict,
    revision_dict,
    revision_stub_dict,
)

router = APIRouter(prefix="/api/content", tags=["content"])


class RevisionIn(BaseModel):
    """Body for adding a revision to a post."""

    body: str


class AttachmentIn(BaseModel):
    """Body for attaching a file to a post."""

    filename: str
    url: str
    size_bytes: int


@router.get("/posts/{post_id}/revisions")
async def revisions_of_post(
    post_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """The revisions of a post."""
    return [
        revision_dict(r) for r in await usecases.revisions_of_post(session, post_id)
    ]


@router.get("/posts/{post_id}/attachments")
async def attachments_of_post(
    post_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """The attachments of a post."""
    return [
        attachment_dict(a) for a in await usecases.attachments_of_post(session, post_id)
    ]


@router.post("/posts/{post_id}/revisions", status_code=201)
async def add_revision(
    post_id: int, payload: RevisionIn, session: SessionDep
) -> dict[str, object]:
    """Add a revision to a post. 404 if the post does not exist."""
    result = await usecases.add_revision(session, post_id, payload.body)
    if isinstance(result, Failure):
        raise http_error(result)
    return revision_dict(result)


@router.post("/posts/{post_id}/attachments", status_code=201)
async def attach_file(
    post_id: int, payload: AttachmentIn, session: SessionDep
) -> dict[str, object]:
    """Attach a file to a post. 404 if the post does not exist."""
    result = await usecases.attach_file(
        session, post_id, payload.filename, payload.url, payload.size_bytes
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return attachment_dict(result)


@router.delete("/attachments/{attachment_id}", status_code=204)
async def remove_attachment(attachment_id: int, session: SessionDep) -> None:
    """Delete an attachment. 404 if the attachment does not exist."""
    result = await usecases.remove_attachment(session, attachment_id)
    if isinstance(result, Failure):
        raise http_error(result)


@router.get("/posts/{post_id}/history")
async def revision_timeline(
    post_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """WHEN a post was edited, newest first — the history, without the histories.

    The same deferred query the other two demos run: `defer()` lives on the query and the query has
    no colour, so this surface cannot start sending the bodies while the other two do not.
    """
    return [
        revision_stub_dict(revision)
        for revision in await usecases.revision_timeline(session, post_id)
    ]
