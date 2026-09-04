"""The four taxonomy pages, as the two SSR demos will ask for them.

A view model is what the two demos SHARE when they draw the same screen, and taxonomy is the domain
that had none: it answered only as JSON, so nothing had ever turned a tag into something a template
can walk. These four are what the pages of phase 3 render.

THE FILTER PAGE IS THE ONE WORTH READING. Its first state is not an error and not a result: nothing
is ticked yet, so no question has been put to the engine. Making that a `Failure` — the way a missing
invoice is one — would hand the view an empty hand and force it to build the screen itself, which is
the exact thing a view model exists to stop. So it is a FIELD, `asked`, and the page renders its tick
boxes either way.

That distinction is also what the underlying refusal means. `posts_with_every_tag` rejects fewer than
two tags because an intersection of one branch is not an intersection; here that same input is just a
screen nobody has finished filling in.

WHAT `checked` IS FOR. The tags a post already carries decide which boxes start ticked, and that is
the state the bridge's duplicate bug used to be invisible behind: with no screen, nobody ever
submitted the same pair twice.
"""

from __future__ import annotations

from snakeorm import SnakeSession

from shared.models import Blog, Post, Tag, TagGroup, User
from shared.usecases import taxonomy_usecases as usecases
from shared.viewmodels import taxonomy_viewmodels as viewmodels


def _world(session: SnakeSession) -> tuple[list[int], list[int]]:
    """Three posts over two tags of two groups: enough for every page to say something different."""
    author = session.add(
        User(username="linus", email="linus@example.com", password_hash="x")
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
    topics = session.add(TagGroup(name="topics"))
    engines = session.add(TagGroup(name="engines"))
    tags = [
        session.add(Tag(name="orm", group_id=topics.id, parent_id=None)).id,
        session.add(Tag(name="sqlite", group_id=engines.id, parent_id=None)).id,
    ]
    session.commit()
    for post_id, picked in zip(posts, ([0, 1], [0], [1]), strict=True):
        for index in picked:
            usecases.tag_post(session, post_id, tags[index])
    return posts, tags


def test_the_tag_list_hangs_every_tag_under_its_group(session: SnakeSession) -> None:
    """The landing page: groups in order, each carrying its own tags and no others."""
    _world(session)

    page = viewmodels.tag_list(session)

    assert [
        (group["name"], [tag["name"] for tag in group["tags"]])
        for group in page["groups"]
    ] == [
        ("engines", ["sqlite"]),
        ("topics", ["orm"]),
    ]
    assert page["tag_count"] == 2


def test_a_group_with_no_tags_still_appears(session: SnakeSession) -> None:
    """An empty group is a group, not a gap: it is where the "new tag" form sends you."""
    _world(session)
    session.add(TagGroup(name="unused"))
    session.commit()

    page = viewmodels.tag_list(session)

    assert ("unused", []) in [
        (group["name"], [tag["name"] for tag in group["tags"]])
        for group in page["groups"]
    ]


def test_the_post_page_ticks_the_tags_the_post_already_carries(
    session: SnakeSession,
) -> None:
    """Every tag is offered; the ones on the post start ticked. That is the whole screen.

    The boxes come in the SAME order as the listing — by group, then by tag — and not by id. Two
    screens of one domain that sort the same tags differently make the reader check, every time,
    whether they are looking at the same set.
    """
    posts, _ = _world(session)

    page = viewmodels.post_tags(session, posts[1])

    assert [
        (choice["group"], choice["name"], choice["checked"])
        for choice in page["choices"]
    ] == [
        ("engines", "sqlite", False),
        ("topics", "orm", True),
    ]


def test_the_filter_asks_nothing_until_two_tags_are_ticked(
    session: SnakeSession,
) -> None:
    """The opening state of the screen: boxes drawn, engine untouched, and it says why.

    Not a `Failure`: a form nobody has filled in yet is not a missing page, and treating it as one
    would leave the view with nothing to render but an error.
    """
    _world(session)

    page = viewmodels.filtered_posts(session, tag_ids=[], without=None)

    assert page["asked"] is False
    assert page["posts"] == []
    assert page["hint"]
    assert len(page["choices"]) == 2


def test_two_ticked_tags_give_the_posts_that_carry_both(session: SnakeSession) -> None:
    """The INTERSECT, through the page: only the post carrying both survives."""
    posts, tags = _world(session)

    page = viewmodels.filtered_posts(session, tag_ids=tags, without=None)

    assert page["asked"] is True
    assert [row["id"] for row in page["posts"]] == [posts[0]]
    assert all(choice["checked"] for choice in page["choices"])


def test_excluding_a_tag_needs_only_one_ticked(session: SnakeSession) -> None:
    """The EXCEPT half: with something to subtract, ONE tag is already a question."""
    posts, tags = _world(session)

    page = viewmodels.filtered_posts(session, tag_ids=[tags[0]], without=tags[1])

    assert page["asked"] is True
    assert [row["id"] for row in page["posts"]] == [posts[1]]
    assert page["excluded"] == "sqlite"
