"""The tag bridge: tagging is IDEMPOTENT, and asking whether a link exists does not load it.

`PostTag` is the one N—N in the catalogue with an explicit bridge, and until this file existed the
two operations that write to it were both wrong in the same direction: they treated a PAIR as if it
were a row with a key.

TAGGING WAS A BLIND `add`. `services.tag_post` built a `PostTag` and inserted it, so tagging the same
post with the same tag twice left TWO bridge rows. Nothing noticed because the only surface was an
API that nobody clicks twice; a screen with checkboxes finds it on the first afternoon. The fix is
`get_or_create`, whose boolean is the point rather than a detail — it is what lets the API answer
201 when it created the link and 200 when it was already there.

UNTAGGING LOADED A ROW IN ORDER TO THROW IT AWAY. `session.first(tagging(...))` fetched the bridge
row only to hand it to `session.delete`, which is two round trips for a `DELETE ... WHERE` of one.
`exists` answers the question that was actually being asked, and `delete_where` deletes by the pair.

WHY THE ASSERTIONS ARE ON THE SQL AND NOT ONLY ON THE ANSWER. Both fixes are invisible from the
outside: the old code and the new one return the same thing. What changed is the number of
statements and their shape, so that is what gets pinned. A test that only checked the return value
would stay green if somebody put the `first(...)` back.

AND THE UNIQUE IS NOT DECORATION. `get_or_create`'s own docstring says it: another transaction fits
between the SELECT and the INSERT, so uniqueness has to live in the DATABASE or it does not exist.
The composite index on `(post_id, tag_id)` is that guarantee, and the last test here is the one that
proves the schema really carries it rather than the model merely declaring it.
"""

from __future__ import annotations

import pytest
from snakeorm import SnakeSession
from snakeorm.debug import capture_queries

from shared.models import Blog, Post, PostTag, Tag, TagGroup, User
from shared.selectors.taxonomy_selectors import tagging
from shared.services import taxonomy_services as services
from shared.usecases import taxonomy_usecases as usecases
from shared.usecases.result import Failure


def _post_and_tag(session: SnakeSession) -> tuple[int, int]:
    """One post and one tag, which is the smallest world in which a bridge row means anything."""
    author = session.add(
        User(username="ada", email="ada@example.com", password_hash="x")
    )
    blog = session.add(
        Blog(title="A blog", slug="a-blog", description=None, owner_id=author.id)
    )
    post = session.add(
        Post(
            title="A post",
            body="...",
            blog_id=blog.id,
            category_id=None,
            author_id=author.id,
        )
    )
    group = session.add(TagGroup(name="topics"))
    tag = session.add(Tag(name="orm", group_id=group.id, parent_id=None))
    session.commit()
    return post.id, tag.id


def _bridge_rows(session: SnakeSession, post_id: int, tag_id: int) -> int:
    """How many bridge rows tie this exact pair, which is the number the duplicate bug moves."""
    return len(session.all(tagging(post_id, tag_id)))


def test_tagging_the_same_pair_twice_leaves_one_row(session: SnakeSession) -> None:
    """The duplicate that the blind `add` used to create, stated as a count."""
    post_id, tag_id = _post_and_tag(session)

    usecases.tag_post(session, post_id, tag_id)
    usecases.tag_post(session, post_id, tag_id)

    assert _bridge_rows(session, post_id, tag_id) == 1


def test_tagging_says_whether_it_created_the_link(session: SnakeSession) -> None:
    """The boolean `get_or_create` exists for: the API answers 201 or 200 with it."""
    post_id, tag_id = _post_and_tag(session)

    _, created_first = services.tag_post(session, post_id, tag_id)
    session.commit()
    _, created_again = services.tag_post(session, post_id, tag_id)
    session.commit()

    assert (created_first, created_again) == (True, False)


def test_tagging_an_already_tagged_post_inserts_nothing(session: SnakeSession) -> None:
    """And it is not just the count: the second call must not reach an INSERT at all.

    The count alone would stay green if somebody inserted and then deleted, or inserted under a
    `ON CONFLICT DO NOTHING` the demos do not use. What is being pinned is that the write is skipped.
    """
    post_id, tag_id = _post_and_tag(session)
    usecases.tag_post(session, post_id, tag_id)

    with capture_queries() as collector:
        usecases.tag_post(session, post_id, tag_id)

    written = [r.sql for r in collector.report().records if "INSERT" in r.sql.upper()]
    assert written == [], collector.report().to_text()


def test_untagging_what_is_not_there_asks_with_an_exists(session: SnakeSession) -> None:
    """The absent link is reported without ever loading the bridge row.

    `EXISTS` in the emitted SQL is the whole assertion: `first(...)` selects the bridge's columns,
    and this is the difference between asking a question and fetching an answer to ignore it.
    """
    post_id, tag_id = _post_and_tag(session)

    with capture_queries() as collector:
        result = usecases.untag_post(session, post_id, tag_id)

    assert result == Failure("not_found")
    emitted = collector.report()
    assert emitted.count == 1, emitted.to_text()
    assert "EXISTS" in emitted.records[0].sql.upper(), emitted.to_text()


def test_untagging_is_the_exists_and_one_delete_by_the_pair(
    session: SnakeSession,
) -> None:
    """Two statements, and the second is a DELETE filtered by BOTH columns of the pair."""
    post_id, tag_id = _post_and_tag(session)
    usecases.tag_post(session, post_id, tag_id)

    with capture_queries() as collector:
        assert usecases.untag_post(session, post_id, tag_id) is None

    emitted = collector.report()
    kinds = [r.sql.split()[0].upper() for r in emitted.records]
    assert kinds == ["SELECT", "DELETE"], emitted.to_text()
    assert emitted.records[1].params == (post_id, tag_id), emitted.to_text()
    assert _bridge_rows(session, post_id, tag_id) == 0


def test_the_database_refuses_the_same_pair_twice(session: SnakeSession) -> None:
    """The UNIQUE that makes `get_or_create` safe, proven where it has to hold: in the schema.

    `get_or_create` is a SELECT followed by an INSERT and says so in its own docstring — two
    transactions can both find nothing and both insert. Only the database can stop that, so the
    model declaring the index is not enough: this inserts the pair twice behind the use case's back
    and demands that the engine be the one to say no.
    """
    post_id, tag_id = _post_and_tag(session)
    session.add(PostTag(post_id=post_id, tag_id=tag_id))
    session.commit()

    with pytest.raises(Exception):  # noqa: B017 - each driver raises its own integrity error
        session.add(PostTag(post_id=post_id, tag_id=tag_id))
        session.commit()


def _three_posts_and_two_tags(session: SnakeSession) -> tuple[list[int], list[int]]:
    """Three posts over two tags: one carries BOTH, one carries only the first, one only the second.

    It is the smallest world in which "all of these tags" and "this one but not that one" give
    different answers from each other AND from "any of these tags". With two posts either question
    could be answered right by accident.
    """
    author = session.add(
        User(username="grace", email="grace@example.com", password_hash="x")
    )
    blog = session.add(
        Blog(title="A blog", slug="b", description=None, owner_id=author.id)
    )
    posts = [
        session.add(
            Post(
                title=f"Post {n}",
                body="...",
                blog_id=blog.id,
                category_id=None,
                author_id=author.id,
            )
        ).id
        for n in range(3)
    ]
    group = session.add(TagGroup(name="topics"))
    tags = [
        session.add(Tag(name=name, group_id=group.id, parent_id=None)).id
        for name in ("orm", "sql")
    ]
    session.commit()
    for post_id, tag_ids in zip(posts, ([0, 1], [0], [1]), strict=True):
        for index in tag_ids:
            usecases.tag_post(session, post_id, tags[index])
    return posts, tags


def test_posts_with_every_tag_keeps_only_the_post_that_carries_them_all(
    session: SnakeSession,
) -> None:
    """The AND over an N—N: carrying one of the two is not carrying both."""
    posts, tags = _three_posts_and_two_tags(session)

    found = usecases.posts_with_every_tag(session, tags)

    assert not isinstance(found, Failure), found
    assert [post.id for post in found] == [posts[0]]


def test_posts_with_every_tag_asks_the_engine_to_intersect(
    session: SnakeSession,
) -> None:
    """And it asks for it as an INTERSECT rather than folding the branches in Python.

    Requiring two tags of an N—N is not a `WHERE`: the two conditions hold on DIFFERENT bridge rows,
    so `tag_id = A AND tag_id = B` matches nothing. Reading both sets and intersecting them in
    Python would give the right answer and carry every post of each tag over the wire to throw most
    of them away. This pins which of the two is happening.
    """
    _, tags = _three_posts_and_two_tags(session)

    with capture_queries() as collector:
        usecases.posts_with_every_tag(session, tags)

    emitted = collector.report()
    assert emitted.count == 1, emitted.to_text()
    assert "INTERSECT" in emitted.records[0].sql.upper(), emitted.to_text()


def test_posts_with_one_tag_and_not_another_subtracts_the_second(
    session: SnakeSession,
) -> None:
    """The EXCLUDE half of the same screen: tagged the first and NOT the second."""
    posts, tags = _three_posts_and_two_tags(session)

    found = usecases.posts_with_tag_but_not(session, tags[0], tags[1])

    assert [post.id for post in found] == [posts[1]]


def test_excluding_a_tag_asks_the_engine_to_subtract(session: SnakeSession) -> None:
    """As an EXCEPT, for the same reason the one above is an INTERSECT."""
    _, tags = _three_posts_and_two_tags(session)

    with capture_queries() as collector:
        usecases.posts_with_tag_but_not(session, tags[0], tags[1])

    emitted = collector.report()
    assert emitted.count == 1, emitted.to_text()
    assert "EXCEPT" in emitted.records[0].sql.upper(), emitted.to_text()


def test_asking_for_every_tag_of_a_single_tag_is_refused(session: SnakeSession) -> None:
    """Fewer than two tags is a DIFFERENT question, and the one that already has an operation.

    Answering it here would make this the operation that quietly does two things: an intersection of
    one set is that set, so the compound would collapse to a plain query and the name would stop
    describing the SQL. `catalog.posts_for_tag` is what "the posts of this tag" means.
    """
    _, tags = _three_posts_and_two_tags(session)

    assert usecases.posts_with_every_tag(session, tags[:1]) == Failure("missing_fields")
    assert usecases.posts_with_every_tag(session, []) == Failure("missing_fields")
