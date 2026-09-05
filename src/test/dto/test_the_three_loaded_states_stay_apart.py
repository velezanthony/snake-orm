"""A relationship is in one of THREE states, and a generated DTO types each of them differently.

    not loaded                  ->  SnakeRelationshipNotLoaded    (no DTO shape at all)
    to-one loaded, no partner   ->  None                          (`AuthorDto | None`)
    to-many loaded, no children ->  []                            (`list[CommentDto]`)

The generator writes the SHAPE and never the query, which is the whole bargain: the ORM shouts when
a relation was not loaded instead of quietly emitting an N+1. That bargain only holds while the
three stay apart. Collapse the first into either of the others and the DTO's `| None` becomes a
promise nothing backs — a response that says `author: AuthorDto` and carries `None`, with the type
checker agreeing all the way to the front end.

Run against a REAL Postgres on purpose. All three states are produced by `session/planning.py` while
it stitches a wide LEFT JOIN row back into objects — `_instantiate_with_compiled` attaches `None`
when every PK position of a chunk is NULL, `plan_to_many_level` attaches `[]` when a parent grouped
nothing. A fake driver would be testing the fake.

The seed makes both answers exist in ONE query: post 1 has an editor and two comments, post 2 has
neither. Same shapes, opposite answers, so a fixture that stopped covering one case would take the
other down with it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm.dialects import PostgresDialect
from snakeorm.drivers import PsycopgDriver
from snakeorm.fields import SnakeRelationshipNotLoaded
from snakeorm.linker import snake_link
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.conftest import NO_SERVER_REASON
from test.dto.loaded_domain import (
    LoadedAuthor,
    LoadedComment,
    LoadedPost,
    create_schema,
    seed,
)
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def loaded_session() -> Iterator[SnakeSession]:
    """A session over the seeded domain, linked."""
    import psycopg2

    try:
        driver = PsycopgDriver.connect(dsn())
    except (
        psycopg2.OperationalError
    ) as error:  # pragma: no cover - depends on the environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")

    create_schema(driver)
    seed(driver)
    driver.commit()
    snake_link()
    session = SnakeSession(driver, PostgresDialect())
    yield session
    driver.close()


def _posts(session: SnakeSession, *, include: bool) -> dict[int, LoadedPost]:
    """Every post by id, loaded with or without its relations."""
    query = SnakeQuery(LoadedPost)
    if include:
        query = query.include(LoadedPost.author, LoadedPost.editor)
    return {row.id: row for row in session.all(query)}


def test_a_relation_nobody_asked_for_shouts(loaded_session: SnakeSession) -> None:
    """State ONE. Reading a relation the query did not load raises, naming the include to add.

    The message is asserted and not just the type: it is what a developer reads at 2am, and it is
    the only thing standing between them and a silent N+1.
    """
    post = _posts(loaded_session, include=False)[1]

    with pytest.raises(
        SnakeRelationshipNotLoaded, match=r"include\(LoadedPost\.author\)"
    ):
        post.author


def test_a_to_many_nobody_asked_for_shouts_too(loaded_session: SnakeSession) -> None:
    """State ONE on a collection. It must NOT come back as an empty list.

    This is the confusion that would hurt most: `[]` is a perfectly good answer for a parent with no
    children, so a collection that returned it when nothing was loaded would be indistinguishable
    from the truth — and a DTO would ship an empty array where rows exist.
    """
    post = _posts(loaded_session, include=False)[1]

    with pytest.raises(
        SnakeRelationshipNotLoaded, match=r"include\(LoadedPost\.comments\)"
    ):
        post.comments


def test_a_loaded_to_one_with_no_partner_is_None(loaded_session: SnakeSession) -> None:
    """State TWO. `editor_id` is NULL, so the LEFT JOIN found nothing and the answer IS `None`.

    Not an error: the query asked, the engine answered, and the answer is that there is no editor.
    That is exactly what the generated `AuthorDto | None` says.
    """
    post = _posts(loaded_session, include=True)[2]

    assert post.editor is None


def test_the_same_relation_loaded_WITH_a_partner_is_the_object(
    loaded_session: SnakeSession,
) -> None:
    """The floor for the test above: the `None` has to mean "no row", not "this never works".

    Without this, an `editor` that was broken for every post would pass the previous assertion.
    """
    post = _posts(loaded_session, include=True)[1]

    assert isinstance(post.editor, LoadedAuthor)
    assert post.editor.username == "grace"


def test_a_loaded_to_many_with_no_children_is_an_empty_list(
    loaded_session: SnakeSession,
) -> None:
    """State THREE. Post 2 has no comments, so the answer is `[]` — never `None`, never a raise.

    This is why the generator writes `list[CommentDto]` without `| None`: a collection is not
    optional, and a parent with no children is a fact about the data rather than an absence.
    """
    query = SnakeQuery(LoadedPost).include(LoadedPost.comments)
    posts = {row.id: row for row in loaded_session.all(query)}

    assert posts[2].comments == []


def test_the_same_collection_WITH_children_carries_them(
    loaded_session: SnakeSession,
) -> None:
    """The floor for the test above: `[]` has to mean "no rows", not "this never loads"."""
    query = SnakeQuery(LoadedPost).include(LoadedPost.comments)
    posts = {row.id: row for row in loaded_session.all(query)}

    assert [comment.body for comment in posts[1].comments] == ["first", "second"]
    assert all(isinstance(comment, LoadedComment) for comment in posts[1].comments)


def test_the_three_states_are_three_different_answers(
    loaded_session: SnakeSession,
) -> None:
    """THE test, said once: the three are pairwise distinguishable in the same run.

    Each of the tests above is about one state, and each would keep passing if two states quietly
    merged somewhere else. This one asks the question the DTO actually depends on — are they three
    answers or two — so it goes red on a merge that the individual tests would let through.

    It covers the unloaded state on BOTH kinds, and that is not symmetry for its own sake. Written
    with only the to-one it survived a real mutation: a `SnakeToMany.__get__` that returned `[]`
    instead of raising went unnoticed here while the dedicated test above caught it. A test whose
    name promises "the three states" and asks about one kind is a name its body cannot pay for.
    """
    unloaded = _posts(loaded_session, include=False)[2]
    loaded = _posts(loaded_session, include=True)[2]
    with_children = {
        row.id: row
        for row in loaded_session.all(
            SnakeQuery(LoadedPost).include(LoadedPost.comments)
        )
    }[2]

    with pytest.raises(
        SnakeRelationshipNotLoaded, match=r"include\(LoadedPost\.editor\)"
    ):
        unloaded.editor
    with pytest.raises(
        SnakeRelationshipNotLoaded, match=r"include\(LoadedPost\.comments\)"
    ):
        unloaded.comments
    assert loaded.editor is None
    assert with_children.comments == []
