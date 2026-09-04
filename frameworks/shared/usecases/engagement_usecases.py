"""engagement domain use cases (comments, reactions, visits), written once.

RECORDING A VISIT IS THE ONE OPERATION HERE THAT DOES NOT KNOW ITS OWN RESULT. `Post.visit_count` is
denormalised and kept by a TRIGGER — the invariant has to hold for writes that never pass through
this ORM, so it lives in the engine — which means the row the caller is holding is out of date the
instant the INSERT lands, and nothing in Python is in a position to work out the new number.
Incrementing it here would be a guess that is wrong the moment two visits are recorded at once.

So the object is REFRESHED instead: the same instance, reloaded from the row the trigger has just
changed. Reading it back with a second query would answer the same number and leave two objects for
one post, free to disagree with each other for as long as both are alive.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from snakeorm import SnakeSession

from shared.models import Comment, Reaction, Visit
from shared.selectors import engagement_selectors as selectors
from shared.services import engagement_services as services
from shared.usecases.result import Failure


@dataclass(frozen=True, slots=True)
class VisitTally:
    """A recorded visit and the post's counter AS THE DATABASE HAS IT once the trigger has run.

    The two travel together because the second is what the caller came for: a page that records a
    visit shows the visit it recorded and the total it just became part of, and a client that had to
    ask again would be reading a number from a later moment than the one it wrote.
    """

    visit: Visit
    visit_count: int


def comments_of_post(session: SnakeSession, post_id: int) -> list[Comment]:
    """A post's comments with their author loaded (one query, no N+1)."""
    return selectors.comments_of_post(session, post_id)


def reactions_of_post(session: SnakeSession, post_id: int) -> list[Reaction]:
    """A post's reactions."""
    return selectors.reactions_of_post(session, post_id)


def plan_for_visits_of_post(session: SnakeSession, post_id: int) -> list[str]:
    """The engine's plan for the visit listing, without running it.

    It explains the SAME colourless query the listing uses, so what is read is what actually runs.
    """
    return session.explain(selectors.visits_of(post_id))


def visits_of_post(session: SnakeSession, post_id: int) -> list[Visit]:
    """A post's recorded visits (traffic metrics)."""
    return selectors.visits_of_post(session, post_id)


def add_comment(
    session: SnakeSession, post_id: int, author_id: int, body: str
) -> Comment | Failure:
    """Adds a comment to a post; `missing_fields` if the body comes in empty."""
    if not body:
        return Failure("missing_fields")
    comment = services.add_comment(session, post_id, author_id, body)
    session.commit()
    return comment


def add_reaction(
    session: SnakeSession, post_id: int, user_id: int, kind: str
) -> Reaction | Failure:
    """Records a reaction to a post; `missing_fields` if the kind is missing."""
    if not kind:
        return Failure("missing_fields")
    reaction = services.add_reaction(session, post_id, user_id, kind)
    session.commit()
    return reaction


def record_visit(
    session: SnakeSession, post_id: int, ip: str, user_agent: str | None = None
) -> VisitTally | Failure:
    """Records a visit and reads back the counter the TRIGGER moved underneath. `not_found` if no post.

    THE ORDER IS THE OPERATION. The post is read BEFORE the write, so what is held afterwards is an
    object from before the trigger ran — which is the honest shape of the problem rather than a
    contrivance: any handler that has already loaded a row and then writes something that fires a
    trigger on it is in exactly this position. `refresh` is the ORM's answer, and it is the only one
    that leaves ONE object for one row.

    The commit comes first because a trigger writes inside the transaction that fired it: refreshing
    before it would read the same row twice within one statement's worth of work and prove nothing
    about the engine having done anything.
    """
    post = session.first(selectors.visited_post(post_id))
    if post is None:
        return Failure("not_found")
    visit = services.record_visit(session, post_id, ip, user_agent)
    session.commit()
    session.refresh(post)
    return VisitTally(visit=visit, visit_count=post.visit_count)


def stream_visits(
    session: SnakeSession, *, post_id: int | None = None
) -> Iterator[Visit]:
    """The traffic log as a STREAM, for the export. `return`, never `yield`, all the way down.

    The rows arrive NARROW — the query names the three columns the file has and leaves the browser
    string behind — which is the half that matters on a table with millions of rows: streaming keeps
    the row COUNT out of memory, and `only()` keeps the row WIDTH off the wire. Neither one does the
    other's job.

    No `Failure` and no probe that the post exists. A filter that matches nothing is an answer — an
    empty file — and spending a statement on a case only a hand-edited URL produces is the call the
    other exports in this layer already made.
    """
    return selectors.stream_visits(session, post_id=post_id)
