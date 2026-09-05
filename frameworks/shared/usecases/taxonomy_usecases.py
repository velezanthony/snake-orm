"""taxonomy domain use cases (groups and tags, tagging posts), written once.

`tag_post`/`untag_post` write to the PostTag bridge table: that is the N:M tag↔post relationship.
"""

from __future__ import annotations

from collections.abc import Sequence

from snakeorm import SnakeSession

from shared.models import Post, PostTag, Tag, TagGroup
from shared.selectors import taxonomy_selectors as selectors
from shared.services import taxonomy_services as services
from shared.usecases.result import Failure


def list_groups(session: SnakeSession) -> list[TagGroup]:
    """Every tag group."""
    return selectors.list_groups(session)


def list_tags(session: SnakeSession) -> list[Tag]:
    """Every tag, with its group loaded."""
    return selectors.list_tags(session)


def tags_of_post(session: SnakeSession, post_id: int) -> list[Tag]:
    """A post's tags (through the PostTag bridge table)."""
    return selectors.tags_of_post(session, post_id)


def posts_with_every_tag(
    session: SnakeSession, tag_ids: Sequence[int]
) -> list[Post] | Failure:
    """The posts carrying ALL of these tags; `missing_fields` with fewer than two.

    The refusal is the honest answer rather than a guard: with one tag the question is "the posts of
    this tag", which is a different operation and already has one. Answering it here would make the
    name lie about the SQL — an intersection of one branch is not an intersection.
    """
    if len(tag_ids) < 2:
        return Failure("missing_fields")
    return session.all(selectors.posts_with_every_tag(tag_ids))


def posts_with_tag_but_not(
    session: SnakeSession, tag_id: int, excluded_tag_id: int
) -> list[Post]:
    """The posts carrying the first tag and NOT the second."""
    return session.all(selectors.posts_with_tag_but_not(tag_id, excluded_tag_id))


def create_tag(
    session: SnakeSession, name: str, group_id: int, parent_id: int | None = None
) -> Tag | Failure:
    """Creates a tag in a group and optionally under another; `missing_fields` on an empty name."""
    if not name:
        return Failure("missing_fields")
    tag = services.create_tag(session, name, group_id, parent_id)
    session.commit()
    return tag


def tag_post(session: SnakeSession, post_id: int, tag_id: int) -> tuple[PostTag, bool]:
    """Tags a post (writes to PostTag) and commits it. Idempotent: tagging twice is one link.

    The second element says whether THIS call created it, which the web layer turns into 201 or 200.
    """
    link, created = services.tag_post(session, post_id, tag_id)
    session.commit()
    return link, created


def untag_post(session: SnakeSession, post_id: int, tag_id: int) -> None | Failure:
    """Removes a tag from a post; `not_found` if that link did not exist."""
    if not services.untag_post(session, post_id, tag_id):
        return Failure("not_found")
    session.commit()
    return None


def tag_breadcrumb(session: SnakeSession, tag_id: int) -> list[Tag] | Failure:
    """Where a tag sits in the taxonomy: the root, then each tag down to this one. ONE statement.

    `not_found` on an empty answer, and the emptiness is the check rather than a probe before it: a
    recursion anchored on a row that is not there returns nothing, so the query that answers the
    question also answers whether there was one. A `SELECT` first would be a second round trip to
    learn what the first one already knows.
    """
    rows = selectors.ancestry(session, tag_id)
    if not rows:
        return Failure("not_found")
    return selectors.order_ancestry(rows, tag_id)


def tag_descendants(session: SnakeSession, tag_id: int) -> list[Tag]:
    """Every tag under this one, at any depth, by name. ONE statement whatever the depth.

    The anchor is dropped: it is the tag the caller named, and the breadcrumb above already ends with
    it. What is left is the SECTION — the part of the catalogue that hangs off this label — and it is
    the answer no `WHERE` can give, because "under" is a chain and a `WHERE` sees one row at a time.
    """
    rows = [tag for tag in selectors.subtree(session, tag_id) if tag.id != tag_id]
    return sorted(rows, key=lambda tag: tag.name)
