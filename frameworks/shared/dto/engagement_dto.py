"""DTOs for the engagement domain (comments, reactions, visits). Flat and JSON-able."""

from __future__ import annotations

from shared.dto import iso
from shared.models import Comment, Reaction, Visit
from shared.usecases.engagement_usecases import VisitTally


def comment_dict(comment: Comment) -> dict[str, object]:
    """A comment as a dict."""
    return {
        "id": comment.id,
        "body": comment.body,
        "post_id": comment.post_id,
        "author_id": comment.author_id,
        "created_at": iso(comment.created_at),
    }


def reaction_dict(reaction: Reaction) -> dict[str, object]:
    """A reaction as a dict."""
    return {
        "id": reaction.id,
        "kind": reaction.kind,
        "post_id": reaction.post_id,
        "user_id": reaction.user_id,
        "created_at": iso(reaction.created_at),
    }


def visit_dict(visit: Visit) -> dict[str, object]:
    """A visit as a dict."""
    return {
        "id": visit.id,
        "post_id": visit.post_id,
        "ip": visit.ip,
        "user_agent": visit.user_agent,
        "visited_at": iso(visit.visited_at),
    }


def visit_tally_dict(tally: VisitTally) -> dict[str, object]:
    """A recorded visit and the post's counter AS THE DATABASE HAS IT once the trigger has run.

    The counter is a top-level field and not something folded into the visit, because it is a fact
    about the POST and not about the row that was just written. A client reading it here is reading
    what the engine says, which is the only place that number exists.
    """
    return {
        "visit": visit_dict(tally.visit),
        "visit_count": tally.visit_count,
    }
