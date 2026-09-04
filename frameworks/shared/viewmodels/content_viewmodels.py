"""content view models: the posts a body has been rewritten for, and one post's history and files.

THE SECTION EXISTS BECAUSE THE OLD REASON FOR IT NOT TO STOPPED HOLDING. "Revisions and attachments
of a post, reached from the blog's own screens" is what the older net wrote next to this domain, and
it was an argument about where the pages belong rather than about whether there should be any: the
blog's editor never grew them, so for as long as it did not, the demo taught in JSON that a post has
a history and taught in HTML that it has none. That was owed, and this is the layer that pays it.

THE DETAIL PAGE ASKS FOR THE SAME ROWS TWICE, AND THAT IS THE PAGE. `revision_timeline` and
`revisions_of_post` are not one read with two widths — the selector next door argues it at length —
they are two questions. "How often has this been rewritten, and when" wants a column of instants;
"what did it say on the ninth of March" wants a body. Drawing them side by side is what makes the
difference visible, and it is the only screen in the demos where a `defer()` and the full read of the
same table appear together: the timeline above is what a person scans, the bodies below are what
they open, and on a post edited two hundred times the first one costs two hundred instants where the
second costs two hundred copies of an article.

WHAT IT COSTS IS AN INSTANCE THAT IS NOT WHOLE, and this layer must never hide that. A timeline row
has no `body`, and reading one RAISES rather than answering an empty string — so `TimelineRow` names
no body and cannot start naming one by accident, exactly as the DTO beside it cannot.

Nothing here decides anything. The use cases validate and commit; what is left is turning rows into
`str` and `int` so a template never walks a relation.
"""

from __future__ import annotations

from typing import TypedDict

from snakeorm import SnakeSession

from shared.usecases import blog_usecases as blog
from shared.usecases import content_usecases as usecases
from shared.usecases.result import Failure


class PostRow(TypedDict):
    """One post on the landing page: who wrote it, and whether it has been published."""

    post_id: int
    title: str
    author: str
    published: bool


class PostIndex(TypedDict):
    """The landing page of the section: the posts whose history and files can be opened."""

    posts: list[PostRow]
    post_count: int


class TimelineRow(TypedDict):
    """One step of a post's history: WHEN it was edited, and deliberately not into what.

    There is no `body` here and there cannot be one. These rows arrive from a query that defers that
    column, so touching it raises; naming it in this shape would turn a loud refusal into a silent
    empty string on the day somebody wired it up.
    """

    revision_id: int
    edited_at: str


class RevisionRow(TypedDict):
    """One revision WITH what the post said: the other question, and the expensive one."""

    revision_id: int
    edited_at: str
    body: str


class AttachmentRow(TypedDict):
    """One attached file: what it is called, where it lives and how big it is."""

    attachment_id: int
    filename: str
    url: str
    size_bytes: int


class PostContentPage(TypedDict):
    """One post's content history: the timeline, the revisions themselves, and the files.

    `error` carries a refused form back to the screen that submitted it — an empty body, a file with
    no name — because a redirect would throw away what the person had typed, which is the one thing a
    form must not do to somebody it has just refused.
    """

    post_id: int
    title: str
    timeline: list[TimelineRow]
    revisions: list[RevisionRow]
    attachments: list[AttachmentRow]
    total_bytes: int
    error: str


def post_index(session: SnakeSession) -> PostIndex:
    """Every post, so a reader can open the history of one. ONE statement, authors already joined.

    It reads through the blog's own use case rather than a second one of this domain's, and that is
    the seam working rather than a shortcut: "every post with its author" is a question this demo
    already answers, and asking it twice from two modules is how two listings start disagreeing about
    what a post is.
    """
    rows: list[PostRow] = [
        {
            "post_id": post.id,
            "title": post.title,
            "author": post.author.username,
            "published": post.published,
        }
        for post in blog.list_posts(session)
    ]
    return {"posts": rows, "post_count": len(rows)}


def post_content(
    session: SnakeSession, post_id: int, *, error: str = ""
) -> PostContentPage | Failure:
    """One post's timeline, its revisions and its attachments. `not_found` if there is no post."""
    post = blog.show_post(session, post_id)
    if isinstance(post, blog.Failure):
        return Failure("not_found")
    attachments = usecases.attachments_of_post(session, post_id)
    return {
        "post_id": post_id,
        "title": post.title,
        "timeline": [
            {
                "revision_id": revision.id,
                "edited_at": revision.edited_at.isoformat(),
            }
            for revision in usecases.revision_timeline(session, post_id)
        ],
        "revisions": [
            {
                "revision_id": revision.id,
                "edited_at": revision.edited_at.isoformat(),
                "body": revision.body,
            }
            for revision in usecases.revisions_of_post(session, post_id)
        ],
        "attachments": [
            {
                "attachment_id": attachment.id,
                "filename": attachment.filename,
                "url": attachment.url,
                "size_bytes": attachment.size_bytes,
            }
            for attachment in attachments
        ],
        "total_bytes": sum(attachment.size_bytes for attachment in attachments),
        "error": error,
    }
