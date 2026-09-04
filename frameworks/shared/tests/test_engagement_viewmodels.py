"""The engagement pages, as the two SSR demos ask for them: the board and one post's sheet.

The domain answered only as JSON until E.3, and the shape it was missing is not a DTO. A board that
ranks posts by traffic and a sheet that carries three forms are things a template walks, and the two
demos have to walk the SAME one or the section drifts the moment somebody edits one of them.

WHAT THIS FILE IS REALLY FOR IS THE COUNTER. `visit_count` is denormalised and kept by a TRIGGER, so
the number on the page cannot be `len(visits)` and cannot be an increment either: the row changes
underneath the object the handler is holding, and two visits landing at once make any arithmetic in
Python a guess. `record_visit` answers with what the engine now says, and the assertion below is that
the page prints THAT — measured on a post whose recent list is deliberately shorter than its counter,
because on a post where the two agree the difference is invisible and a wrong page passes.
"""

from __future__ import annotations

from snakeorm import SnakeQuery, SnakeSession, SnakeUtc
from snakeorm.migration import emit_create_trigger

from shared.models import Blog, Post, User, Visit
from shared.models.engagement_models import visit_counter
from shared.usecases import engagement_usecases as usecases
from shared.usecases.result import Failure
from shared.viewmodels import engagement_viewmodels as viewmodels


def _install_the_trigger(session: SnakeSession) -> None:
    """Creates the declared trigger on the session's engine, as a migration would.

    The conftest builds the schema from the MODELS, which knows nothing about triggers — they live in
    the registry, not in a table. Installing it here through the same emitter a migration uses is
    what keeps the assertion about the counter measuring the engine rather than this file.
    """
    for statement in emit_create_trigger(visit_counter, session.dialect):
        session._driver.execute(statement, ())  # noqa: SLF001 - the harness has no public hook
    session.commit()


def _world(session: SnakeSession) -> tuple[int, int, int]:
    """Two posts by one author, and the id of somebody who can comment. Enough to rank two rows."""
    author = session.add(
        User(username="ada", email="ada@example.com", password_hash="x")
    )
    blog = session.add(
        Blog(title="A blog", slug="b", description=None, owner_id=author.id)
    )
    quiet = session.add(
        Post(
            title="Quiet post",
            body="...",
            blog_id=blog.id,
            category_id=None,
            author_id=author.id,
        )
    )
    busy = session.add(
        Post(
            title="Busy post",
            body="...",
            blog_id=blog.id,
            category_id=None,
            author_id=author.id,
        )
    )
    session.commit()
    return busy.id, quiet.id, author.id


def test_the_board_ranks_the_posts_by_the_counter_and_totals_them(
    session: SnakeSession,
) -> None:
    """Busiest first, with the author beside each row and the totals across them."""
    _install_the_trigger(session)
    busy, quiet, _ = _world(session)
    for _ in range(3):
        usecases.record_visit(session, busy, "10.0.0.1")
    usecases.record_visit(session, quiet, "10.0.0.2")

    page = viewmodels.traffic_board(session)

    assert [(row["title"], row["author"], row["visits"]) for row in page["posts"]] == [
        ("Busy post", "ada", 3),
        ("Quiet post", "ada", 1),
    ]
    assert (page["post_count"], page["total_visits"]) == (2, 4)


def test_the_sheet_carries_the_three_lists_of_one_post(session: SnakeSession) -> None:
    """Comments, reactions and visits, each flattened to primitives a template can print.

    The comment's author and the reaction's user arrive as NAMES rather than ids, which is the whole
    reason this layer exists: the selectors `include` them, so the template never walks a relation
    and no query is paid per row inside the renderer.
    """
    _install_the_trigger(session)
    busy, _, author = _world(session)
    usecases.add_comment(session, busy, author, "First!")
    usecases.add_reaction(session, busy, author, "clap")
    usecases.record_visit(session, busy, "10.0.0.7")

    sheet = viewmodels.engagement_sheet(session, busy)

    assert not isinstance(sheet, Failure)
    assert sheet["title"] == "Busy post"
    assert [(c["author"], c["body"]) for c in sheet["comments"]] == [("ada", "First!")]
    assert [(r["kind"], r["user"]) for r in sheet["reactions"]] == [("clap", "ada")]
    assert [v["ip"] for v in sheet["visits"]] == ["10.0.0.7"]
    assert sheet["recorded"] is False


def test_the_counter_on_the_page_is_the_engine_s_and_not_the_length_of_the_list(
    session: SnakeSession,
) -> None:
    """The number comes from the row the TRIGGER moved, on a post where the two figures differ.

    The visits are inserted directly, so the counter climbs without a single row reaching the list
    this page draws — and then one visit is recorded through the use case. A page that printed
    `len(visits)` would answer 1 here and would have looked right on every post where the recent
    list happens to be the whole history, which is every post in a small fixture.
    """
    _install_the_trigger(session)
    busy, _, _ = _world(session)
    for _ in range(4):
        session.add(
            Visit(
                post_id=busy,
                ip="10.0.0.9",
                user_agent=None,
                visited_at=SnakeUtc.now(),
            )
        )
    session.commit()

    page = viewmodels.record_visit(session, busy, "10.0.0.1")

    assert not isinstance(page, Failure)
    assert page["visit_count"] == 5
    assert page["recorded"] is True
    assert session.all(SnakeQuery(Post).filter(Post.id == busy))[0].visit_count == 5


def test_a_post_that_is_not_there_refuses_on_both_operations(
    session: SnakeSession,
) -> None:
    """The sheet and the button answer the same `not_found`, so one 404 page serves both."""
    _install_the_trigger(session)
    _world(session)

    assert viewmodels.engagement_sheet(session, 9999) == Failure("not_found")
    assert viewmodels.record_visit(session, 9999, "10.0.0.1") == Failure("not_found")
