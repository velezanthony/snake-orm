"""engagement view models: the traffic board, one post's engagement, and the traffic export.

THE DOMAIN HAS A SECTION NOW, which is what it was owed. It
used to have none — comments, reactions and visits were written by the blog's own screens and read
back only as JSON — and the export sat on the API surface for exactly that reason rather than because
a file belongs there. The section arriving is what moves it across, and the entry in
`test_the_page_and_the_api_reach_one_usecase.py` said so before the section existed.

TWO PAGES AND A FILE, and the split is the domain's rather than a taxonomy filled in: the board is
every post with the counter a TRIGGER keeps, the sheet is one post's comments, reactions and visits
with the three forms that write them, and the export is the whole traffic log streamed.

THE COUNTER IS NOT ADDED UP HERE, and it could not be. `Post.visit_count` is denormalised and
maintained by a trigger, so the only place the number exists is the row — which is why `record_visit`
answers with a `VisitTally` and why the page prints what came back rather than `len(visits)`. A page
that counted the rows it happens to be drawing would be right on a post with four visits and wrong on
one with four million, and it would be wrong QUIETLY.

WHY THE EXPORT LIVES IN A VIEW MODEL AND NOT IN A ROUTE. `CsvExport` is imported from the inventory
module rather than redefined, exactly as the orders export imports it: it is the SHAPE of a download
and there is one of those, not one per domain. What each domain owns is its header and how a row of
its table becomes text, and those two are here so the three demos cannot each format an instant a
different way.

THE ROWS ARE NARROW AND THE STREAM IS LAZY, and they are two different economies that are easy to
confuse. `iterate()` keeps the row COUNT out of memory: a million visits never exist as a million
objects. `only()` keeps the row WIDTH off the wire: the `user_agent` this file does not print never
leaves the server at all. Drop either one and the export is still correct and still wrong — the first
without the second reads a gigabyte of browser strings in order to discard them, and the second
without the first still builds the whole list before writing a byte.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TypedDict

from snakeorm import SnakeSession

from shared.models import Visit
from shared.usecases import blog_usecases as blog
from shared.usecases import engagement_usecases as usecases
from shared.usecases.result import Failure
from shared.viewmodels.inventory_viewmodels import CsvExport


class TrafficRow(TypedDict):
    """One post on the board: who wrote it and how many visits the trigger has counted for it."""

    post_id: int
    title: str
    author: str
    visits: int


class TrafficBoard(TypedDict):
    """The landing page of the section: every post, ordered by the counter, with the totals."""

    posts: list[TrafficRow]
    post_count: int
    total_visits: int


class CommentRow(TypedDict):
    """One comment: who wrote it, what it says and when."""

    comment_id: int
    author: str
    body: str
    written_at: str


class ReactionRow(TypedDict):
    """One reaction: which kind it is and who left it."""

    reaction_id: int
    kind: str
    user: str


class VisitRow(TypedDict):
    """One recorded visit: the address it came from and the instant it landed."""

    visit_id: int
    ip: str
    visited_at: str


class EngagementSheet(TypedDict):
    """One post's engagement: the counter, the three lists, and whether a visit was just recorded.

    `visit_count` is the number the DATABASE has and never a length. `recorded` is what turns the
    same shape into the answer to a button: the page after a POST is the page before it plus a line
    saying the trigger moved, and drawing it from a second template would be two screens that look
    alike until one of them is edited.
    """

    post_id: int
    title: str
    visit_count: int
    comments: list[CommentRow]
    reactions: list[ReactionRow]
    visits: list[VisitRow]
    recorded: bool


VISIT_EXPORT_FILENAME = "visits.csv"
"""What the downloaded file is called, in all three demos.

It lives here and not in a route for the reason the other exports give: a file called `visits.csv` in
one demo and `traffic.csv` in another is the drift this whole layer exists to stop, one storey down.
The asynchronous demo cannot use the `CsvExport` container — its rows arrive from an async iterator —
so it reads this name and the header beside it instead, which is the half that must not differ.
"""

VISIT_EXPORT_HEADER: tuple[str, ...] = ("visit_id", "post_id", "ip", "visited_at")
"""The columns of the traffic CSV, and the browser string is deliberately not among them.

It is the header that decides what the query may leave behind, and that is the right way round: the
file names its columns, the fragment defers everything else, and the ORM raises if this list ever
grows a name the query did not bring. A header written to match the table would have made the
narrowing invisible and the mistake silent.
"""


def visit_cells(visit: Visit) -> tuple[str, ...]:
    """One visit as CSV text. It touches NO column the query left behind, and it cannot start to.

    Reading `visit.user_agent` here raises rather than answering `None` — the rows arrive from an
    `only()` — so the day somebody adds a fifth column to the header, this function fails loudly
    instead of writing a file full of empty strings.
    """
    return (
        str(visit.id),
        str(visit.post_id),
        visit.ip,
        visit.visited_at.isoformat(),
    )


def visits_export(session: SnakeSession, *, post_id: int | None = None) -> CsvExport:
    """The traffic log as CSV rows, STREAMED: ONE statement, narrow rows, flat memory.

    The generator expression is the implementation for the reason the other two exports give: a
    `yield` here would make this function lazy instead of the ORM, and `iterate`'s refusal of an
    unstreamable query would stop firing next to the call that caused it.

    `post_id` narrows the QUERY and not the writer. Filtering while writing would read every visit of
    every post in order to throw most of them away, on the one page whose whole subject is not
    reading things it does not need.
    """
    visits: Iterator[Visit] = usecases.stream_visits(session, post_id=post_id)
    return CsvExport(
        filename=VISIT_EXPORT_FILENAME,
        header=VISIT_EXPORT_HEADER,
        rows=(visit_cells(visit) for visit in visits),
    )


def traffic_board(session: SnakeSession) -> TrafficBoard:
    """Every post with the visit counter the TRIGGER keeps, busiest first, and the totals.

    ONE statement: the posts arrive with their author already joined, which is the read the blog's
    own listing makes, asked here for a different question. Walking `post.author` in the template
    would be the same page at one query per row — the N+1 inside the renderer that this layer exists
    to keep out.

    The ordering and the total are done over rows that have ALREADY ARRIVED. That is not a shortcut:
    `visit_count` is a column on the post, so the whole board is on the rows the first statement
    brought, and a second round trip to sort four hundred integers would be a query to answer a
    question that is already answered.
    """
    rows: list[TrafficRow] = sorted(
        (
            {
                "post_id": post.id,
                "title": post.title,
                "author": post.author.username,
                "visits": post.visit_count,
            }
            for post in blog.list_posts(session)
        ),
        key=lambda row: (-row["visits"], row["title"]),
    )
    return {
        "posts": rows,
        "post_count": len(rows),
        "total_visits": sum(row["visits"] for row in rows),
    }


def engagement_sheet(session: SnakeSession, post_id: int) -> EngagementSheet | Failure:
    """One post's comments, reactions and visits, with the counter as the DATABASE has it."""
    post = blog.show_post(session, post_id)
    if isinstance(post, blog.Failure):
        return Failure("not_found")
    return _sheet(session, post_id, post.title, post.visit_count, recorded=False)


def record_visit(
    session: SnakeSession, post_id: int, ip: str
) -> EngagementSheet | Failure:
    """Records a visit and redraws the sheet with the counter the trigger has just moved.

    A WRITE in a view model, and it is the same exception `logistics.reroute` argues: nothing is
    DECIDED here. The use case reads the post, writes the visit, commits and `refresh`es the object
    the trigger changed underneath it — and what comes back is the number the engine now holds. This
    layer formats that answer and asks for the three lists beside it, which is what the GET does for
    the same screen.

    `visit_count` comes off the tally and NEVER off `len(visits)`. The list below it is the recent
    traffic and the counter is every visit there has ever been; on the seeded volume table those two
    are not the same number, and a page that conflated them would be quietly wrong on exactly the
    posts the counter exists for.
    """
    tally = usecases.record_visit(session, post_id, ip)
    if isinstance(tally, Failure):
        return tally
    post = blog.show_post(session, post_id)
    title = post.title if not isinstance(post, blog.Failure) else ""
    return _sheet(session, post_id, title, tally.visit_count, recorded=True)


def _sheet(
    session: SnakeSession,
    post_id: int,
    title: str,
    visit_count: int,
    *,
    recorded: bool,
) -> EngagementSheet:
    """The three lists of one post, formatted. Written once because two operations answer one shape.

    `engagement_sheet` reads it and `record_visit` writes and then reads it, and they are the same
    screen — the second is the first after a button. Two formatters would be two screens that agree
    until somebody edits one of them.
    """
    return {
        "post_id": post_id,
        "title": title,
        "visit_count": visit_count,
        "comments": [
            {
                "comment_id": comment.id,
                "author": comment.author.username,
                "body": comment.body,
                "written_at": comment.created_at.isoformat(),
            }
            for comment in usecases.comments_of_post(session, post_id)
        ],
        "reactions": [
            {
                "reaction_id": reaction.id,
                "kind": reaction.kind,
                "user": reaction.user.username,
            }
            for reaction in usecases.reactions_of_post(session, post_id)
        ],
        "visits": [
            {
                "visit_id": visit.id,
                "ip": visit.ip,
                "visited_at": visit.visited_at.isoformat(),
            }
            for visit in usecases.visits_of_post(session, post_id)
        ],
        "recorded": recorded,
    }
