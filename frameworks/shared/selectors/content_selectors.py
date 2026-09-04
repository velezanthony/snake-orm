"""content domain — SELECTORS: reads of a post's revisions and attachments.

Every framework re-exports them from `apps/content/selectors.py`.

Each read comes in TWO pieces: the FRAGMENT builds a `SnakeQuery` and does not run it, the EXECUTOR
takes a session and runs it. Only the executor has a colour, so the SQL is written once and both the
synchronous demos and the asynchronous one in `shared/aio/` run the very same query.
"""

from __future__ import annotations

from snakeorm import SnakeQuery, SnakeSession

from shared.models import Attachment, PostRevision


def revisions_of(post_id: int) -> SnakeQuery[PostRevision]:
    """FRAGMENT: a post's revision history, most recent first."""
    return (
        SnakeQuery(PostRevision)
        .filter(PostRevision.post_id == post_id)
        .order_by(PostRevision.edited_at.desc())
    )


def revision_timeline_of(post_id: int) -> SnakeQuery[PostRevision]:
    """FRAGMENT: WHEN a post was edited, without the article repeated once per edit. NOT run.

    THIS IS NOT `revisions_of` WITH A NARROWER SELECT — it is the other question. "What did this
    post say on the ninth of March" wants a body and there is one operation for it; "how often has
    this been rewritten, and when" wants a list of instants, and on a post edited two hundred times
    the first shape answers it by sending two hundred copies of the article.

    `defer()` is what states that, and it states it POSITIVELY BY EXCLUSION: everything the row has
    except the one column that is the size of a page. Written as an `only()` it would be a list of
    the columns that happen to exist today, and the column somebody adds tomorrow would go missing
    from a timeline that never mentioned it.

    What it costs is an instance that is not whole, and the ORM refuses to hide that: reading `body`
    off one of these rows RAISES rather than handing back an empty string. The DTO beside this one
    does not name it, and it cannot start naming it by accident.
    """
    return (
        SnakeQuery(PostRevision)
        .defer(PostRevision.body)
        .filter(PostRevision.post_id == post_id)
        .order_by(PostRevision.edited_at.desc())
    )


def attachments_of(post_id: int) -> SnakeQuery[Attachment]:
    """FRAGMENT: a post's attached files, in the order they were attached."""
    return (
        SnakeQuery(Attachment)
        .filter(Attachment.post_id == post_id)
        .order_by(Attachment.id.asc())
    )


def attachment_by_id(attachment_id: int) -> SnakeQuery[Attachment]:
    """FRAGMENT: ONE attachment, if it is there.

    A read, so it lives here, even though the only caller that wants it is the service that DELETES
    it: removing an attachment is "find it, delete it", and the asynchronous twin has to find it
    with exactly this `WHERE` rather than with a second one that merely looks alike today.
    """
    return SnakeQuery(Attachment).filter(Attachment.id == attachment_id)


def revisions_of_post(session: SnakeSession, post_id: int) -> list[PostRevision]:
    """A post's revision history, most recent first."""
    return session.all(revisions_of(post_id))


def attachments_of_post(session: SnakeSession, post_id: int) -> list[Attachment]:
    """A post's attached files."""
    return session.all(attachments_of(post_id))


def revision_timeline(session: SnakeSession, post_id: int) -> list[PostRevision]:
    """When a post was edited, newest first, with no body attached. One statement, narrow rows."""
    return session.all(revision_timeline_of(post_id))
