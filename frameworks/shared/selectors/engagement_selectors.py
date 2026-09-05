"""engagement domain — SELECTORS: pure reads (a post's comments, reactions and visits).

Every framework re-exports them from its `apps/engagement/selectors.py`.

Each read comes in TWO pieces: the FRAGMENT builds a `SnakeQuery` and does not run it, the EXECUTOR
takes a session and runs it. Only the executor has a colour, so the SQL is written once and both the
synchronous demos and the asynchronous one in `shared/aio/` run the very same query — including the
`include` that keeps the comment listing from becoming an N+1, which is the one line here that would
hurt most to have in two copies drifting apart.
"""

from __future__ import annotations

from collections.abc import Iterator

from snakeorm import SnakeQuery, SnakeSession

from shared.models import Comment, Post, Reaction, Visit

# How many rows of a stream travel from the server at a time. The same default the inventory export
# uses and for the same reasons: a round trip per row is what makes streaming slower than
# materialising, and fifty thousand at a time gives back the flat memory the page exists for.
EXPORT_CHUNK = 500


def visited_post(post_id: int) -> SnakeQuery[Post]:
    """FRAGMENT: the post a visit is about to be recorded against, as an INSTANCE. NOT run.

    An instance and not a count, and that is the whole reason this exists. `visit_count` is kept by
    a TRIGGER, so the row changes UNDERNEATH whoever holds it: the object read here is stale the
    moment the visit lands, and `session.refresh(post)` is what teaches that same object what the
    database now says. Re-querying instead would hand back a SECOND object for one row, and the two
    would disagree about the same post for as long as both were alive.
    """
    return SnakeQuery(Post).filter(Post.id == post_id)


def comments_of(post_id: int) -> SnakeQuery[Comment]:
    """FRAGMENT: a post's comments with their author loaded, newest first."""
    return (
        SnakeQuery(Comment)
        .filter(Comment.post_id == post_id)
        .include(Comment.author)
        .order_by(Comment.created_at.desc())
    )


def reactions_of(post_id: int) -> SnakeQuery[Reaction]:
    """FRAGMENT: a post's reactions with the user who reacted."""
    return (
        SnakeQuery(Reaction)
        .filter(Reaction.post_id == post_id)
        .include(Reaction.user)
        .order_by(Reaction.id.asc())
    )


def visits_of(post_id: int) -> SnakeQuery[Visit]:
    """FRAGMENT: a post's recorded visits, most recent first."""
    return (
        SnakeQuery(Visit)
        .filter(Visit.post_id == post_id)
        .order_by(Visit.visited_at.desc())
    )


def comments_of_post(session: SnakeSession, post_id: int) -> list[Comment]:
    """A post's comments, with their author loaded, newest first."""
    return session.all(comments_of(post_id))


def reactions_of_post(session: SnakeSession, post_id: int) -> list[Reaction]:
    """A post's reactions, with the user who reacted."""
    return session.all(reactions_of(post_id))


def visits_of_post(session: SnakeSession, post_id: int) -> list[Visit]:
    """A post's recorded visits, most recent first."""
    return session.all(visits_of(post_id))


def visits_to_export(post_id: int | None = None) -> SnakeQuery[Visit]:
    """FRAGMENT: the traffic log as the FILE has it — post, address and instant. NOT run.

    `only()` IS THE POINT OF THIS QUERY, and the table is the reason. `visits` is the volume table —
    millions of rows at the seeded scales — and it carries a `user_agent` that no column of this file
    prints: a browser string is around a hundred bytes, so over ten million rows it is a gigabyte
    read off the disk, pushed through the socket and decoded into Python, for nothing.

    What it costs is an instance that is NOT whole, and the ORM makes that cost loud rather than
    silent: reading `user_agent` off one of these rows RAISES instead of answering `None`. That
    refusal is why this is a safe thing to do here and a dangerous thing to do on a page that might
    later print one more field — the writer below names three columns and cannot grow a fourth
    without being told.

    The primary key comes back whether it was asked for or not, which is what keeps these rows
    rows: an instance with no identity could not be matched, refreshed or written back.

    NO `limit()`. A bounded export is a page of results wearing a download's name, and it would make
    every test that says this streams pass over a query that never had to.

    The order is the instant with the id as the tiebreaker: two visits inside the same second are
    ordinary on a volume table, and an unstable order in a file somebody diffs against yesterday's
    is a file that looks changed when nothing changed.
    """
    query = (
        SnakeQuery(Visit)
        .only(Visit.post_id, Visit.ip, Visit.visited_at)
        .order_by(Visit.visited_at.asc(), Visit.id.asc())
    )
    if post_id is not None:
        query = query.filter(Visit.post_id == post_id)
    return query


def stream_visits(
    session: SnakeSession,
    *,
    post_id: int | None = None,
    chunk: int = EXPORT_CHUNK,
) -> Iterator[Visit]:
    """The visits one at a time, WITHOUT the result ever existing whole in memory.

    `return`, never `yield`, for the reason the inventory export sets out at length: written as a
    generator this function would not run a line of its body until somebody asked for the first row,
    so `iterate`'s guard against an unstreamable query would fire far from the call that caused it.
    Returning the iterator keeps the guard eager and the execution lazy.
    """
    return session.iterate(visits_to_export(post_id), chunk=chunk)
