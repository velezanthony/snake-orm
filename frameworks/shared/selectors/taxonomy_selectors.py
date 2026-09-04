"""taxonomy domain — SELECTORS: reads of groups, tags and a post's tags (N—N).

Every framework re-exports them from `apps/taxonomy/selectors.py`.

Each read comes in TWO pieces: the FRAGMENT builds a `SnakeQuery` and does not run it, the EXECUTOR
takes a session and runs it. Only the executor has a colour, so the SQL is written once and both the
synchronous demos and the asynchronous one in `shared/aio/` run the very same query.
"""

from __future__ import annotations

from collections.abc import Sequence

from snakeorm import SnakeCompound, SnakeQuery, SnakeRecursive, SnakeSession

from shared.models import Post, PostTag, Tag, TagGroup

# Bounds the RESULT, far above any taxonomy a person would build. It is NOT the cycle guard it was
# written to be: measured on Postgres, a cyclic walk with `order_by()` and a LIMIT never returns.
# What stops the walk is `distinct=True` on the recursions below.
TREE_LIMIT = 500


def all_groups() -> SnakeQuery[TagGroup]:
    """FRAGMENT: every tag group, by name."""
    return SnakeQuery(TagGroup).order_by(TagGroup.name.asc())


def all_tags() -> SnakeQuery[Tag]:
    """FRAGMENT: every tag with its group loaded, by name. The `include` is the JOIN, not an N+1."""
    return SnakeQuery(Tag).include(Tag.group).order_by(Tag.name.asc())


def tagging(post_id: int, tag_id: int) -> SnakeQuery[PostTag]:
    """FRAGMENT: the bridge row that ties ONE post to ONE tag, if it is there.

    A read, so it lives here, even though the only caller that wants it is the service that DELETES
    it: untagging is "find the link, delete the link", and the asynchronous twin has to find it with
    exactly this `WHERE` rather than with a second one that looks alike today.
    """
    return SnakeQuery(PostTag).filter(
        PostTag.post_id == post_id, PostTag.tag_id == tag_id
    )


def list_groups(session: SnakeSession) -> list[TagGroup]:
    """Every tag group, by name."""
    return session.all(all_groups())


def list_tags(session: SnakeSession) -> list[Tag]:
    """Every tag with its group loaded, by name."""
    return session.all(all_tags())


def tags_of(post_id: int) -> SnakeQuery[Tag]:
    """The query for a post's tags, NOT executed: more can still be stacked on top.

    It resolves the N—N with a SUBQUERY and not with two round trips: `as_scalar` projects the
    bridge's `tag_id` filtered by post, and `Tag.id.in_(sub)` consumes it. It is the portable shape,
    and the one `catalog.posts_for_tag` already used — the piece was in the ORM and went unused here.

    Pulling the ids into Python and asking again made two round trips instead of one, and the second
    one carried a list of ids that grows with the data: a thousand tags, a thousand `IN` parameters.
    """
    bridged = (
        SnakeQuery(PostTag).filter(PostTag.post_id == post_id).as_scalar(PostTag.tag_id)
    )
    return SnakeQuery(Tag).filter(Tag.id.in_(bridged))


def tags_of_post(session: SnakeSession, post_id: int) -> list[Tag]:
    """A post's tags, by name. Executes what `tags_of` composes."""
    return session.all(tags_of(post_id).order_by(Tag.name.asc()))


def posts_for(tag_id: int) -> SnakeQuery[Post]:
    """FRAGMENT: the posts carrying ONE tag, through the same bridge subquery as `tags_of`.

    The mirror image of `tags_of`, and it exists as a fragment because the two questions below are
    built by COMPOSING it: one branch per tag, handed to the engine as a set operation.
    """
    bridged = (
        SnakeQuery(PostTag).filter(PostTag.tag_id == tag_id).as_scalar(PostTag.post_id)
    )
    return SnakeQuery(Post).filter(Post.id.in_(bridged))


def posts_with_every_tag(tag_ids: Sequence[int]) -> SnakeCompound[Post]:
    """FRAGMENT: the posts carrying ALL of these tags, as an `INTERSECT` of one branch per tag.

    IT IS NOT A `WHERE`, and that is the whole reason this is here. The conditions hold on DIFFERENT
    bridge rows — one row says `tag_id = A` and another says `tag_id = B` — so `tag_id = A AND
    tag_id = B` matches nothing at all. The two shapes that do work are a self-join per extra tag,
    which grows a JOIN every time somebody ticks a box, and this one, which grows a branch.

    Folding it in Python instead (read each tag's posts, intersect the sets) gives the same answer
    and drags every post of every tag over the wire to discard most of them. The engine already
    knows how to do this.

    TWO OR MORE, and the caller is the one that checks: an intersection of one set is that set, so
    with a single tag this would silently stop being a compound and the name would stop describing
    the SQL. "The posts of this tag" is `posts_for`, one line above.
    """
    branches = [posts_for(tag_id) for tag_id in tag_ids]
    compound = branches[0].intersect(branches[1])
    for branch in branches[2:]:
        compound = compound.intersect(branch)
    return compound.order_by(Post.id.asc())


def posts_with_tag_but_not(tag_id: int, excluded_tag_id: int) -> SnakeCompound[Post]:
    """FRAGMENT: the posts carrying the first tag and NOT the second, as an `EXCEPT`.

    The exclude half of the same screen. `NOT IN` over the bridge says the same thing and asks the
    planner to decide what to do with a negated subquery; `EXCEPT` states the subtraction, which is
    what the question is.
    """
    return posts_for(tag_id).except_(posts_for(excluded_tag_id)).order_by(Post.id.asc())


def subtree_of(tag_id: int) -> SnakeRecursive[Tag]:
    """FRAGMENT: a tag AND every tag underneath it, at any depth, in ONE statement. NOT run.

    THE HOP IS THE WHOLE THING. `on=(Tag.parent_id, Tag.id)` reads "join the next level's
    `parent_id` onto what has accumulated", which walks DOWNWARDS; the same pair the other way round
    walks up, and `ancestry_of` below is exactly that and nothing else.

    There is no shape in a plain SELECT that answers this. Two `include`s reach a grandchild and
    stop; a chain of `IN` subqueries is one statement per level written by hand and it has to know
    the depth in advance. The honest alternative is a loop in Python asking for one level at a time,
    which is an N+1 whose N is the depth of somebody else's data.

    The anchor row comes back with the rest — a recursion starts from it — so the caller that wants
    the descendants ALONE is the one that drops it, and does so knowing the id it asked for.
    """
    return (
        SnakeQuery(Tag)
        .filter(Tag.id == tag_id)
        .recursive(on=(Tag.parent_id, Tag.id), distinct=True)
        .limit(TREE_LIMIT)
    )


def ancestry_of(tag_id: int) -> SnakeRecursive[Tag]:
    """FRAGMENT: a tag and every tag ABOVE it, up to the root. The breadcrumb, NOT run.

    The same recursion as `subtree_of` with the pair of columns swapped, which the ORM documents as
    a legitimate query rather than a trick: `on=(Tag.id, Tag.parent_id)` joins the next row's `id`
    onto the accumulated `parent_id`, so each step climbs one level.

    It comes back UNORDERED — a CTE is a set — and a breadcrumb is a chain, so the ordering is done
    by the use case from the `parent_id` links the rows already carry. Asking SQL for it would mean
    a depth column and a `LEVEL` the emitter does not offer, to sort at most a handful of rows that
    are already in memory.
    """
    return (
        SnakeQuery(Tag)
        .filter(Tag.id == tag_id)
        .recursive(on=(Tag.id, Tag.parent_id), distinct=True)
        .limit(TREE_LIMIT)
    )


def subtree(session: SnakeSession, tag_id: int) -> list[Tag]:
    """A tag and everything under it, at any depth. Executes what `subtree_of` composes."""
    return session.all(subtree_of(tag_id))


def ancestry(session: SnakeSession, tag_id: int) -> list[Tag]:
    """A tag and everything above it, up to the root. Executes what `ancestry_of` composes."""
    return session.all(ancestry_of(tag_id))


def order_ancestry(rows: Sequence[Tag], tag_id: int) -> list[Tag]:
    """The rows of `ancestry_of` as the CHAIN they describe: root first, the asked-for tag last.

    A recursive CTE answers with a SET, and a breadcrumb is an ORDER. The links are already in the
    rows — every one of them carries the `parent_id` it was reached by — so the chain is walked here,
    over at most a handful of objects that are already in memory. Asking the engine for it would mean
    a depth column this emitter does not offer, to sort what a browser is about to print.

    It is shared by both colours because it is the shape of the ANSWER and not a way of getting it:
    a second copy in `shared/aio/` is how the two demos come to draw two different breadcrumbs out of
    one database.

    A row whose parent is missing from the set ENDS the walk. That is a root reached normally, and it
    is also the shape a hand-edited `parent_id` leaves behind — either way the chain stops rather than
    looping, which is the second half of the guard `TREE_LIMIT` starts.
    """
    by_id = {tag.id: tag for tag in rows}
    chain: list[Tag] = []
    current = by_id.get(tag_id)
    while current is not None and current.id not in {tag.id for tag in chain}:
        chain.append(current)
        current = by_id.get(current.parent_id) if current.parent_id else None
    return list(reversed(chain))
