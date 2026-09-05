"""taxonomy domain (groups, tags, tagging), asked of an `AsyncSession`.

The twin of `shared/usecases/taxonomy_usecases.py`: same names, same parameters, same answers. The
queries come from `shared/selectors/taxonomy_selectors.py` untouched — a `SnakeQuery` has no colour,
so the N—N subquery behind `tags_of` is the same object on both paths and cannot drift into two.
"""

from __future__ import annotations

from collections.abc import Sequence

from snakeorm import AsyncSession

from shared.models import Post, PostTag, Tag, TagGroup
from shared.selectors.taxonomy_selectors import (
    all_groups,
    all_tags,
    ancestry_of,
    order_ancestry,
    subtree_of,
    tagging,
    tags_of,
)
from shared.selectors.taxonomy_selectors import (
    posts_with_every_tag as posts_with_every_tag_query,
)
from shared.selectors.taxonomy_selectors import (
    posts_with_tag_but_not as posts_with_tag_but_not_query,
)
from shared.usecases.result import Failure


async def list_groups(session: AsyncSession) -> list[TagGroup]:
    """Every tag group, by name."""
    return await session.all(all_groups())


async def list_tags(session: AsyncSession) -> list[Tag]:
    """Every tag with its group loaded, by name: one JOIN, not one query per tag."""
    return await session.all(all_tags())


async def tags_of_post(session: AsyncSession, post_id: int) -> list[Tag]:
    """A post's tags (through the PostTag bridge table), by name."""
    return await session.all(tags_of(post_id).order_by(Tag.name.asc()))


async def posts_with_every_tag(
    session: AsyncSession, tag_ids: Sequence[int]
) -> list[Post] | Failure:
    """The posts carrying ALL of these tags; `missing_fields` with fewer than two.

    The `INTERSECT` is built by the same fragment the synchronous twin uses: a compound has no
    colour either, so the branches cannot drift into a second shape on this path.
    """
    if len(tag_ids) < 2:
        return Failure("missing_fields")
    return await session.all(posts_with_every_tag_query(tag_ids))


async def posts_with_tag_but_not(
    session: AsyncSession, tag_id: int, excluded_tag_id: int
) -> list[Post]:
    """The posts carrying the first tag and NOT the second (`EXCEPT`)."""
    return await session.all(posts_with_tag_but_not_query(tag_id, excluded_tag_id))


async def create_tag(
    session: AsyncSession, name: str, group_id: int, parent_id: int | None = None
) -> Tag | Failure:
    """Creates a tag in a group and optionally under another; `missing_fields` on an empty name."""
    if not name:
        return Failure("missing_fields")
    tag = await session.add(Tag(name=name, group_id=group_id, parent_id=parent_id))
    await session.commit()
    return tag


async def tag_post(
    session: AsyncSession, post_id: int, tag_id: int
) -> tuple[PostTag, bool]:
    """Tags a post (writes to PostTag) and commits it. Idempotent: tagging twice is one link.

    The `tagging` fragment is the same object the synchronous twin looks up with, so the SELECT half
    of `get_or_create` cannot drift into a second `WHERE` that merely looks alike today.
    """
    link, created = await session.get_or_create(
        tagging(post_id, tag_id),
        lambda: PostTag(post_id=post_id, tag_id=tag_id),
    )
    await session.commit()
    return link, created


async def untag_post(
    session: AsyncSession, post_id: int, tag_id: int
) -> None | Failure:
    """Removes a tag from a post; `not_found` if that link did not exist.

    `exists` and then `delete_where` by the pair: the same two statements as the synchronous twin,
    and neither of them loads the bridge row in order to throw it away.
    """
    if not await session.exists(tagging(post_id, tag_id)):
        return Failure("not_found")
    await session.delete_where(tagging(post_id, tag_id))
    await session.commit()
    return None


async def tag_breadcrumb(session: AsyncSession, tag_id: int) -> list[Tag] | Failure:
    """Where a tag sits in the taxonomy: the root, then each tag down to this one. ONE statement.

    The recursion comes from `shared/selectors/taxonomy_selectors.py` untouched — a `SnakeRecursive`
    has no colour either — and the chain is ordered by the SAME `order_ancestry` the synchronous twin
    uses, imported rather than rewritten. Written twice, the day one of them changed the walk would
    be the day the two demos printed two different breadcrumbs out of one database.
    """
    rows = await session.all(ancestry_of(tag_id))
    if not rows:
        return Failure("not_found")
    return order_ancestry(rows, tag_id)


async def tag_descendants(session: AsyncSession, tag_id: int) -> list[Tag]:
    """Every tag under this one, at any depth, by name. ONE statement whatever the depth."""
    rows = [tag for tag in await session.all(subtree_of(tag_id)) if tag.id != tag_id]
    return sorted(rows, key=lambda tag: tag.name)
