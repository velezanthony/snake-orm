"""content domain use cases (a post's revisions and attachments), written once."""

from __future__ import annotations

from snakeorm import SnakeSession

from shared.models import Attachment, PostRevision
from shared.selectors import content_selectors as selectors
from shared.services import content_services as services
from shared.usecases.result import Failure


def revisions_of_post(session: SnakeSession, post_id: int) -> list[PostRevision]:
    """A post's revision history, most recent first."""
    return selectors.revisions_of_post(session, post_id)


def revision_timeline(session: SnakeSession, post_id: int) -> list[PostRevision]:
    """WHEN a post was edited, newest first — the history, not the histories.

    The sibling of `revisions_of_post` and a different question from it: this one answers how often
    and when, and it does so without dragging one copy of the article per edit across the wire. The
    rows come back without their `body`, and reading it off one of them raises rather than pretending
    the post was ever empty.
    """
    return selectors.revision_timeline(session, post_id)


def attachments_of_post(session: SnakeSession, post_id: int) -> list[Attachment]:
    """A post's attachments."""
    return selectors.attachments_of_post(session, post_id)


def add_revision(
    session: SnakeSession, post_id: int, body: str
) -> PostRevision | Failure:
    """Saves a new revision of a post's body; `missing_fields` if the body comes in empty."""
    if not body:
        return Failure("missing_fields")
    revision = services.add_revision(session, post_id, body)
    session.commit()
    return revision


def attach_file(
    session: SnakeSession, post_id: int, filename: str, url: str, size_bytes: int
) -> Attachment | Failure:
    """Attaches a file to a post; `missing_fields` if the name or the URL is missing."""
    if not (filename and url):
        return Failure("missing_fields")
    attachment = services.attach_file(session, post_id, filename, url, size_bytes)
    session.commit()
    return attachment


def remove_attachment(session: SnakeSession, attachment_id: int) -> None | Failure:
    """Deletes an attachment; `not_found` if it does not exist."""
    if not services.remove_attachment(session, attachment_id):
        return Failure("not_found")
    session.commit()
    return None
