"""engagement domain (comments, reactions, visits), asked of an `AsyncSession`.

The twin of `shared/usecases/engagement_usecases.py`: same names, same parameters, same answers. The
queries come from `shared/selectors/engagement_selectors.py` untouched — a `SnakeQuery` has no
colour, so the `include(Comment.author)` that keeps the comment listing to ONE statement is the same
object on both paths and cannot become two that drift.

The writes are rebuilt here rather than borrowed from `shared/services/engagement_services.py`, for
the same reason the other twins do it: a service is `session.add(...)`, which is precisely the
coloured half. The timestamps stay where the synchronous services put them —- set by the code and
not by a model default — because a `datetime.now()` frozen at import time is the bug that decision
was made to avoid.
"""

from __future__ import annotations


from collections.abc import AsyncIterator

from snakeorm import SnakeUtc, AsyncSession

from shared.models import Comment, Reaction, Visit
from shared.selectors.engagement_selectors import (
    EXPORT_CHUNK,
    comments_of,
    reactions_of,
    visited_post,
    visits_of,
    visits_to_export,
)
from shared.usecases.engagement_usecases import VisitTally
from shared.usecases.result import Failure


async def comments_of_post(session: AsyncSession, post_id: int) -> list[Comment]:
    """A post's comments with their author loaded (one query, no N+1)."""
    return await session.all(comments_of(post_id))


async def plan_for_visits_of_post(session: AsyncSession, post_id: int) -> list[str]:
    """The engine's plan for the visit listing, without running it.

    It explains the SAME colourless `visits_of(post_id)` the listing itself uses, so what is read is
    what actually runs and not a lookalike rewritten for the panel — which is the way this kind of
    tool usually starts lying.

    The lines come back as the engine writes them: the three do not agree on the shape of a plan.
    """
    return await session.explain(visits_of(post_id))


async def reactions_of_post(session: AsyncSession, post_id: int) -> list[Reaction]:
    """A post's reactions, with the user who reacted."""
    return await session.all(reactions_of(post_id))


async def visits_of_post(session: AsyncSession, post_id: int) -> list[Visit]:
    """A post's recorded visits (traffic metrics), most recent first."""
    return await session.all(visits_of(post_id))


async def add_comment(
    session: AsyncSession, post_id: int, author_id: int, body: str
) -> Comment | Failure:
    """Adds a comment to a post; `missing_fields` if the body comes in empty."""
    if not body:
        return Failure("missing_fields")
    comment = await session.add(
        Comment(
            body=body,
            post_id=post_id,
            author_id=author_id,
            created_at=SnakeUtc.now(),
        )
    )
    await session.commit()
    return comment


async def add_reaction(
    session: AsyncSession, post_id: int, user_id: int, kind: str
) -> Reaction | Failure:
    """Records a reaction to a post; `missing_fields` if the kind is missing."""
    if not kind:
        return Failure("missing_fields")
    reaction = await session.add(
        Reaction(
            kind=kind,
            post_id=post_id,
            user_id=user_id,
            created_at=SnakeUtc.now(),
        )
    )
    await session.commit()
    return reaction


async def record_visit(
    session: AsyncSession, post_id: int, ip: str, user_agent: str | None = None
) -> VisitTally | Failure:
    """Records a visit and reads back the counter the TRIGGER moved underneath. `not_found` if no post.

    The same three steps in the same order as the synchronous twin, and the order is the operation:
    the post is held from BEFORE the write, the commit lets the trigger's UPDATE land, and `refresh`
    teaches that same object what the row now says. `VisitTally` is imported rather than redefined —
    it is a plain dataclass with nothing coloured about it, and a second definition would be a second
    place for the two answers to drift.
    """
    post = await session.first(visited_post(post_id))
    if post is None:
        return Failure("not_found")
    visit = await session.add(
        Visit(
            post_id=post_id,
            ip=ip,
            user_agent=user_agent,
            visited_at=SnakeUtc.now(),
        )
    )
    await session.commit()
    await session.refresh(post)
    return VisitTally(visit=visit, visit_count=post.visit_count)


async def stream_visits(
    session: AsyncSession, *, post_id: int | None = None
) -> AsyncIterator[Visit]:
    """The traffic log as a STREAM, for the CSV route this demo serves and the other two do not.

    `async def` for the net rather than for an `await` this body needs: `AsyncSession.iterate()`
    hands back the async iterator immediately, exactly as the synchronous `iterate()` hands back a
    plain one. The cost lands on the caller, who writes `async for visit in await
    stream_visits(session)`, and the same trade is argued at length in the inventory twin.
    """
    return session.iterate(visits_to_export(post_id), chunk=EXPORT_CHUNK)
