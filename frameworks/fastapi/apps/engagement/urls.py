"""Router of the engagement domain (post comments, reactions and visits): a thin JSON API.

Every endpoint parses the request (Pydantic), calls the use case with flat parameters and translates
the result into JSON (data -> DTO, `Failure` -> HTTPException). Zero queries, zero `commit` here.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from apps import exports
from apps.engagement import usecases
from apps.engagement.usecases import Failure
from apps.deps import SessionDep, http_error
from shared.config import async_session_over
from shared.dto.engagement_dto import (
    comment_dict,
    reaction_dict,
    visit_dict,
    visit_tally_dict,
)
from shared.viewmodels.engagement_viewmodels import (
    VISIT_EXPORT_FILENAME,
    VISIT_EXPORT_HEADER,
    visit_cells,
)

router = APIRouter(prefix="/api/engagement", tags=["engagement"])


class CommentIn(BaseModel):
    """Body for adding a comment to a post."""

    author_id: int
    body: str


class ReactionIn(BaseModel):
    """Body for adding a reaction to a post."""

    user_id: int
    kind: str


class VisitIn(BaseModel):
    """Body for recording a visit to a post (the user agent is optional)."""

    ip: str
    user_agent: str | None = None


@router.get("/posts/{post_id}/comments")
async def comments_of_post(
    post_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """The comments of a post."""
    return [comment_dict(c) for c in await usecases.comments_of_post(session, post_id)]


@router.get("/posts/{post_id}/reactions")
async def reactions_of_post(
    post_id: int, session: SessionDep
) -> list[dict[str, object]]:
    """The reactions of a post."""
    return [
        reaction_dict(r) for r in await usecases.reactions_of_post(session, post_id)
    ]


@router.get("/posts/{post_id}/visits")
async def visits_of_post(post_id: int, session: SessionDep) -> list[dict[str, object]]:
    """The visits of a post."""
    return [visit_dict(v) for v in await usecases.visits_of_post(session, post_id)]


@router.post("/posts/{post_id}/comments", status_code=201)
async def add_comment(
    post_id: int, payload: CommentIn, session: SessionDep
) -> dict[str, object]:
    """Add a comment to a post. 404 if the post does not exist."""
    result = await usecases.add_comment(
        session, post_id, payload.author_id, payload.body
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return comment_dict(result)


@router.post("/posts/{post_id}/reactions", status_code=201)
async def add_reaction(
    post_id: int, payload: ReactionIn, session: SessionDep
) -> dict[str, object]:
    """Add a reaction to a post. 404 if the post does not exist."""
    result = await usecases.add_reaction(
        session, post_id, payload.user_id, payload.kind
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return reaction_dict(result)


@router.post("/posts/{post_id}/visits", status_code=201)
async def record_visit(
    post_id: int, payload: VisitIn, session: SessionDep
) -> dict[str, object]:
    """Record a visit and report the counter the TRIGGER wrote. 404 if the post is not there.

    `visit_count` comes back off the row the trigger changed, through `await session.refresh(post)`
    on the object the use case was already holding — not from a sum computed here, which would be
    wrong the moment two visits land at once.
    """
    result = await usecases.record_visit(
        session, post_id, payload.ip, payload.user_agent
    )
    if isinstance(result, Failure):
        raise http_error(result)
    return visit_tally_dict(result)


@router.get("/visits/export")
async def visits_export(request: Request, post: int | None = None) -> StreamingResponse:
    """The whole traffic log as a STREAMED CSV. The asynchronous half of the streaming pair.

    THE ONE ROUTE IN THIS DEMO THAT DOES NOT TAKE `SessionDep`, and the reason is the response type.
    A `StreamingResponse` body is pulled after the endpoint returns, and `get_session` gives the
    pooled connection back in its `finally` — so a generator reading from it would be asking a
    connection that has already been handed to somebody else. This one opens a session of its own
    and `apps/exports.py` closes it when the download ends or is abandoned.

    The stream is built EAGERLY here: `iterate()` refuses a query it cannot stream, and the refusal
    has to land on this endpoint with a 500 rather than three lines into a body already sent as 200.

    `?post=` narrows the QUERY and not the writer.
    """
    session = async_session_over(await request.app.state.snake_pool.acquire())
    try:
        visits = await usecases.stream_visits(session, post_id=post)
    except Exception:
        await session.close()
        raise
    return exports.csv_download(
        session,
        filename=VISIT_EXPORT_FILENAME,
        header=VISIT_EXPORT_HEADER,
        rows=(visit_cells(visit) async for visit in visits),
    )
