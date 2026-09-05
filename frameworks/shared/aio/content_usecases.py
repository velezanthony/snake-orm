"""content domain (a post's revisions and attachments), asked of an `AsyncSession`.

The twin of `shared/usecases/content_usecases.py`: same names, same parameters, same answers. The
queries come from `shared/selectors/content_selectors.py` untouched — a `SnakeQuery` has no colour,
so both paths run the very same object and cannot drift into two that merely look alike.

The writes do NOT come from `shared/services/content_services.py`, and that asymmetry is the honest
one: a service holds `session.add(...)` and `session.delete(...)`, which is exactly the coloured
half. Rebuilding those two lines here costs two lines; sharing them would cost a colourless service
layer that this domain has no other reason to want.
"""

from __future__ import annotations


from snakeorm import SnakeUtc, AsyncSession

from shared.models import Attachment, PostRevision
from shared.selectors.content_selectors import (
    attachment_by_id,
    attachments_of,
    revision_timeline_of,
    revisions_of,
)
from shared.usecases.result import Failure


async def revisions_of_post(session: AsyncSession, post_id: int) -> list[PostRevision]:
    """A post's revision history, most recent first."""
    return await session.all(revisions_of(post_id))


async def revision_timeline(session: AsyncSession, post_id: int) -> list[PostRevision]:
    """WHEN a post was edited, newest first — the history, not the histories.

    The same deferred query the synchronous twin runs, imported rather than rebuilt: `defer()` is a
    property of the QUERY, so a second spelling here is how one demo comes to send the bodies while
    the other two do not.
    """
    return await session.all(revision_timeline_of(post_id))


async def attachments_of_post(session: AsyncSession, post_id: int) -> list[Attachment]:
    """A post's attachments, in the order they were attached."""
    return await session.all(attachments_of(post_id))


async def add_revision(
    session: AsyncSession, post_id: int, body: str
) -> PostRevision | Failure:
    """Saves a new revision of a post's body; `missing_fields` if the body comes in empty."""
    if not body:
        return Failure("missing_fields")
    revision = await session.add(
        PostRevision(post_id=post_id, body=body, edited_at=SnakeUtc.now())
    )
    await session.commit()
    return revision


async def attach_file(
    session: AsyncSession, post_id: int, filename: str, url: str, size_bytes: int
) -> Attachment | Failure:
    """Attaches a file to a post; `missing_fields` if the name or the URL is missing."""
    if not (filename and url):
        return Failure("missing_fields")
    attachment = await session.add(
        Attachment(post_id=post_id, filename=filename, url=url, size_bytes=size_bytes)
    )
    await session.commit()
    return attachment


async def remove_attachment(
    session: AsyncSession, attachment_id: int
) -> None | Failure:
    """Deletes an attachment; `not_found` if it does not exist."""
    attachment = await session.first(attachment_by_id(attachment_id))
    if attachment is None:
        return Failure("not_found")
    await session.delete(attachment)
    await session.commit()
    return None
