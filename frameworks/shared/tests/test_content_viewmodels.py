"""The content pages: the posts, and one post's history and attached files.

THE ASSERTION THAT MATTERS IS THE NARROW ONE. The detail page reads the revisions TWICE — a
`defer(PostRevision.body)` for the timeline and the full rows underneath — and those are two
questions rather than one read at two widths. What makes the first one safe is that the ORM refuses:
a deferred column raises when it is touched instead of answering an empty string. So the shape this
layer emits for a timeline row must not carry a body, and the test below asserts the ABSENCE by
name — because the failure it guards against is a page that silently prints nothing.

The rest is the ordinary contract of this layer: primitives only, `Failure` handed back untouched,
and a refused form's reason carried on the page rather than redirected away.
"""

from __future__ import annotations

import pytest

from snakeorm import SnakeColumnNotLoaded, SnakeSession

from shared.models import Blog, Post, User
from shared.usecases import content_usecases as usecases
from shared.usecases.result import Failure
from shared.viewmodels import content_viewmodels as viewmodels


def _world(session: SnakeSession) -> int:
    """One published post by one author: the smallest thing that has a history at all."""
    author = session.add(
        User(username="ada", email="ada@example.com", password_hash="x")
    )
    blog = session.add(
        Blog(title="A blog", slug="b", description=None, owner_id=author.id)
    )
    post = session.add(
        Post(
            title="On indexes",
            body="...",
            published=True,
            blog_id=blog.id,
            category_id=None,
            author_id=author.id,
        )
    )
    session.commit()
    return post.id


def test_the_listing_flattens_a_post_to_what_a_row_prints(
    session: SnakeSession,
) -> None:
    """Title, author and state — and the author is a NAME, so no template walks a relation."""
    _world(session)

    page = viewmodels.post_index(session)

    assert page["post_count"] == 1
    assert [
        (row["title"], row["author"], row["published"]) for row in page["posts"]
    ] == [("On indexes", "ada", True)]


def test_the_timeline_carries_no_body_and_the_revisions_do(
    session: SnakeSession,
) -> None:
    """The two panels of the page are the two reads, and only one of them pays for the article.

    The timeline row is asserted to have NO `body` key at all rather than an empty one. That is the
    difference between a narrowing that is visible and a narrowing that is silent: the rows behind it
    raise when the column is touched, and a shape that named it would turn that refusal into a blank.
    """
    post_id = _world(session)
    usecases.add_revision(session, post_id, "first draft")
    usecases.add_revision(session, post_id, "second draft")

    page = viewmodels.post_content(session, post_id)

    assert not isinstance(page, Failure)
    assert len(page["timeline"]) == 2
    assert all("body" not in step for step in page["timeline"])
    assert [revision["body"] for revision in page["revisions"]] == [
        "second draft",
        "first draft",
    ]


def test_reading_the_deferred_body_raises_rather_than_answering_nothing(
    session: SnakeSession,
) -> None:
    """The refusal the shape above depends on, asserted where it happens.

    Without this, `"body" not in step` would only be a fact about a dictionary. With it, the reason
    the dictionary is built that way is a fact about the ORM: the timeline's rows genuinely cannot
    hand over an article, so the narrow page cannot start printing one by accident.
    """
    post_id = _world(session)
    usecases.add_revision(session, post_id, "first draft")

    (revision,) = usecases.revision_timeline(session, post_id)

    with pytest.raises(SnakeColumnNotLoaded):
        _ = revision.body


def test_the_attachments_come_with_the_total_the_page_prints(
    session: SnakeSession,
) -> None:
    """The files, and the sum added up over rows that have already arrived."""
    post_id = _world(session)
    usecases.attach_file(session, post_id, "plan.pdf", "/files/plan.pdf", 900)
    usecases.attach_file(session, post_id, "notes.txt", "/files/notes.txt", 100)

    page = viewmodels.post_content(session, post_id)

    assert not isinstance(page, Failure)
    assert [row["filename"] for row in page["attachments"]] == ["plan.pdf", "notes.txt"]
    assert page["total_bytes"] == 1000


def test_a_refused_form_travels_back_on_the_page_that_submitted_it(
    session: SnakeSession,
) -> None:
    """The reason is a FIELD, not a redirect: a redirect loses what the person had typed."""
    post_id = _world(session)

    page = viewmodels.post_content(session, post_id, error="A revision needs a body.")

    assert not isinstance(page, Failure)
    assert page["error"] == "A revision needs a body."


def test_a_post_that_is_not_there_refuses(session: SnakeSession) -> None:
    """`not_found` and never an empty page, which would say the post exists and is blank."""
    _world(session)

    assert viewmodels.post_content(session, 9999) == Failure("not_found")
