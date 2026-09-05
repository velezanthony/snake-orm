"""taxonomy domain — SERVICES: create tags and tag/untag posts (the N—N).

Every framework re-exports them from `apps/taxonomy/services.py`.
"""

from __future__ import annotations

from snakeorm import SnakeSession

from shared.models import PostTag, Tag
from shared.selectors.taxonomy_selectors import tagging


def create_tag(
    session: SnakeSession, name: str, group_id: int, parent_id: int | None = None
) -> Tag:
    """Creates a tag inside a group and, optionally, UNDER another tag.

    `parent_id` defaults to nothing because a root is the ordinary case: most labels sit at the top
    of the taxonomy, and a form that forced a parent would have to invent one. Passing it is what
    grows the tree the breadcrumb walks.
    """
    return session.add(Tag(name=name, group_id=group_id, parent_id=parent_id))


def tag_post(session: SnakeSession, post_id: int, tag_id: int) -> tuple[PostTag, bool]:
    """Tags a post, IDEMPOTENTLY. Gives the link and whether this call is the one that created it.

    A blind `add` is what this used to be, and tagging twice left two bridge rows for one fact. The
    boolean is not a courtesy: it is what lets the endpoint answer 201 when it created the link and
    200 when it was already there, which is the difference between an idempotent POST and a lie.
    """
    return session.get_or_create(
        tagging(post_id, tag_id),
        lambda: PostTag(post_id=post_id, tag_id=tag_id),
    )


def untag_post(session: SnakeSession, post_id: int, tag_id: int) -> bool:
    """Removes a tag from a post. `False` if it was not tagged.

    Two statements and neither of them loads the row. `exists` asks the question that is actually
    being asked — the caller wants a yes or a no, not a bridge row it is about to discard — and
    `delete_where` deletes by the PAIR, which is what identifies a link here. The `id` column is a
    surrogate nobody outside this table names.
    """
    if not session.exists(tagging(post_id, tag_id)):
        return False
    session.delete_where(tagging(post_id, tag_id))
    return True
