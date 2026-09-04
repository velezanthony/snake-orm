"""A post's edit history WITHOUT the article repeated once per edit: `defer()` earning its place.

`post_revisions` carries a `body`, and a body is the size of a page. Two questions hang off that
table and they are not the same one: "what did this post say on the ninth of March" wants a body and
has an operation of its own, and "how often has this been rewritten, and when" wants a list of
instants. Answering the second with the first is how a history sidebar comes to send two hundred
copies of an article to draw two hundred dates.

WHY `defer()` AND NOT `only()`, which is the choice this file is really about. Naming the columns to
KEEP would freeze the list at whatever the table has today: the column somebody adds next month would
be missing from a timeline that never mentioned it, silently. Naming the one to LEAVE says what is
actually meant — everything except the wide one — and it keeps saying it as the table grows.

AND THE COST IS MADE LOUD BY THE ORM, not by this file. A row that arrives without its `body` carries
a sentinel there, so reading it RAISES instead of answering an empty string. That is what makes the
DTO beside it safe: it cannot start printing a body by accident, because the accident is an exception.
"""

from __future__ import annotations

import pytest
from snakeorm import SnakeQuery, SnakeSession, SnakeUtc
from snakeorm.core.exceptions import SnakeColumnNotLoaded
from snakeorm.debug import capture_queries

from shared.dto.content_dto import revision_stub_dict
from shared.models import Post, PostRevision
from shared.selectors import content_selectors as selectors
from shared.usecases import content_usecases as usecases


def _post_with_history(session: SnakeSession, edits: int) -> int:
    """A seeded post rewritten `edits` times, each revision carrying a body of its own."""
    post_id = session.all(SnakeQuery(Post).limit(1))[0].id
    for index in range(edits):
        session.add(
            PostRevision(
                post_id=post_id,
                body=f"version {index}, and the whole article after it",
                edited_at=SnakeUtc.now(),
            )
        )
    session.commit()
    return post_id


def test_the_timeline_does_not_ask_the_database_for_the_bodies(
    session: SnakeSession,
) -> None:
    """The SELECT names every column except `body`. That is the whole feature, stated as SQL."""
    sql, _ = selectors.revision_timeline_of(1).to_sql(session.dialect)

    assert '"body"' not in sql
    assert '"edited_at"' in sql and '"post_id"' in sql and '"id"' in sql


def test_the_sibling_question_still_carries_them(session: SnakeSession) -> None:
    """`revisions_of` is untouched, and the pair is the point: two questions, two queries.

    Without this line the narrowing could quietly become the only way to read a revision, and "what
    did this post say" would stop being answerable at all.
    """
    sql, _ = selectors.revisions_of(1).to_sql(session.dialect)

    assert '"body"' in sql


def test_reading_the_body_off_a_timeline_row_raises(seeded: SnakeSession) -> None:
    """A deferred column is a refusal, not an empty string.

    Without the sentinel the descriptor would fall through to the column's default and a sidebar
    would render blank bodies that nobody would question — a wrong answer with no error.
    """
    post_id = _post_with_history(seeded, 3)

    rows = usecases.revision_timeline(seeded, post_id)

    assert len(rows) >= 3
    with pytest.raises(SnakeColumnNotLoaded, match="body"):
        rows[0].body


def test_the_dto_serialises_a_timeline_row_without_touching_the_body(
    seeded: SnakeSession,
) -> None:
    """The narrow read and the narrow document are ONE decision, and this is where they meet.

    The DTO naming `body` would raise on every row rather than print a blank, so the two halves
    cannot drift apart in silence: the day one of them changes, the other one fails.
    """
    post_id = _post_with_history(seeded, 2)

    document = revision_stub_dict(usecases.revision_timeline(seeded, post_id)[0])

    assert set(document) == {"id", "post_id", "edited_at"}
    assert document["post_id"] == post_id


def test_the_timeline_is_one_statement_and_newest_first(seeded: SnakeSession) -> None:
    """One query, ordered by when the edit happened: a history is read from the last change back."""
    post_id = _post_with_history(seeded, 4)

    with capture_queries() as collector:
        rows = usecases.revision_timeline(seeded, post_id)

    assert len(collector.report().records) == 1
    assert [row.edited_at for row in rows] == sorted(
        (row.edited_at for row in rows), reverse=True
    )
