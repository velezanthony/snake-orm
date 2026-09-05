"""content domain — SERVICES: writes (save a revision, attach a file).

Every framework re-exports them from `apps/content/services.py`.
"""

from __future__ import annotations


from snakeorm import SnakeUtc, SnakeSession

from shared.models import Attachment, PostRevision
from shared.selectors.content_selectors import attachment_by_id


def add_revision(session: SnakeSession, post_id: int, body: str) -> PostRevision:
    """Saves a revision (version) of a post's body."""
    return session.add(
        PostRevision(post_id=post_id, body=body, edited_at=SnakeUtc.now())
    )


def attach_file(
    session: SnakeSession, post_id: int, filename: str, url: str, size_bytes: int
) -> Attachment:
    """Attaches a file to a post."""
    return session.add(
        Attachment(post_id=post_id, filename=filename, url=url, size_bytes=size_bytes)
    )


def remove_attachment(session: SnakeSession, attachment_id: int) -> bool:
    """Deletes an attachment by id. `False` if it did not exist."""
    attachment = session.first(attachment_by_id(attachment_id))
    if attachment is None:
        return False
    session.delete(attachment)
    return True
