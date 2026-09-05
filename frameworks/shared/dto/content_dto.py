"""DTOs for the content domain (a post's revisions and attachments). Flat and JSON-able."""

from __future__ import annotations

from shared.dto import iso
from shared.models import Attachment, PostRevision


def revision_dict(revision: PostRevision) -> dict[str, object]:
    """A post revision as a dict."""
    return {
        "id": revision.id,
        "post_id": revision.post_id,
        "body": revision.body,
        "edited_at": iso(revision.edited_at),
    }


def revision_stub_dict(revision: PostRevision) -> dict[str, object]:
    """One step of a post's history: when it was edited, and nothing else it was edited INTO.

    It names no `body` on purpose, and not as an economy: the rows it serialises arrive with that
    column deliberately left behind, so touching it here would raise rather than print an empty
    string. The narrow read and the narrow document are one decision written in two places, and this
    is the half a client sees.
    """
    return {
        "id": revision.id,
        "post_id": revision.post_id,
        "edited_at": iso(revision.edited_at),
    }


def attachment_dict(attachment: Attachment) -> dict[str, object]:
    """An attachment as a dict."""
    return {
        "id": attachment.id,
        "post_id": attachment.post_id,
        "filename": attachment.filename,
        "url": attachment.url,
        "size_bytes": attachment.size_bytes,
    }
