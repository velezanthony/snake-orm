"""The accounts pages: the role catalogue with its directory of people, and one person's grants.

The grants screen is `taxonomy`'s tick boxes with different nouns, and the test below asserts it in
those terms on purpose: every role is offered, the held ones are marked, and the catalogue does not
shrink as somebody collects roles. A screen that only listed what was MISSING would have nowhere to
put the button that takes one away, and the pair of writes this domain has would stop being visible
as a pair.

THE DIRECTORY COMES FROM THE BLOG'S AGGREGATE, and that is a seam rather than a borrowing. "Each user
with their post count" is a question this demo already answers in one statement, so the roles page
links from it instead of growing a second "list the users" read that only one of the two would ever
be looked at again.
"""

from __future__ import annotations

from snakeorm import SnakeSession

from shared.models import Blog, Post, User
from shared.usecases import accounts_usecases as usecases
from shared.usecases.result import Failure
from shared.viewmodels import accounts_viewmodels as viewmodels


def _world(session: SnakeSession) -> tuple[int, list[int]]:
    """One author with one post, and two roles to hand out."""
    author = session.add(
        User(username="ada", email="ada@example.com", password_hash="x")
    )
    blog = session.add(
        Blog(title="A blog", slug="b", description=None, owner_id=author.id)
    )
    session.add(
        Post(
            title="On indexes",
            body="...",
            blog_id=blog.id,
            category_id=None,
            author_id=author.id,
        )
    )
    session.commit()
    roles = []
    for name in ("editor", "reviewer"):
        role = usecases.create_role(session, name)
        assert not isinstance(role, Failure)
        roles.append(role.id)
    return author.id, roles


def test_the_directory_carries_the_roles_and_the_people(session: SnakeSession) -> None:
    """Two statements: this domain's catalogue, and the blog's typed aggregate beside it."""
    _world(session)

    page = viewmodels.role_directory(session)

    assert [role["name"] for role in page["roles"]] == ["editor", "reviewer"]
    assert page["role_count"] == 2
    assert [(p["username"], p["post_count"]) for p in page["people"]] == [("ada", 1)]
    assert page["error"] == ""


def test_a_refused_role_travels_back_on_the_page_that_submitted_it(
    session: SnakeSession,
) -> None:
    """The reason is a FIELD, not a redirect: a redirect loses what the person had typed."""
    _world(session)

    page = viewmodels.role_directory(session, error="A role needs a name.")

    assert page["error"] == "A role needs a name."


def test_every_role_is_offered_and_the_held_ones_are_marked(
    session: SnakeSession,
) -> None:
    """The tick boxes: the catalogue whole, with what this person holds flagged on it.

    The held role is still in `choices`, which is the assertion that matters. Offering only what is
    missing would make the screen unable to withdraw anything, and `revoke_role` would have no
    button — a write reachable from the API and from no page, which is the divergence E.3 closed.
    """
    user_id, roles = _world(session)
    usecases.assign_role(session, user_id, roles[0])

    page = viewmodels.user_roles(session, user_id)

    assert page["held"] == ["editor"]
    assert [(c["name"], c["held"]) for c in page["choices"]] == [
        ("editor", True),
        ("reviewer", False),
    ]


def test_somebody_who_holds_nothing_gets_an_answer_and_not_an_error(
    session: SnakeSession,
) -> None:
    """An empty grant list is an ANSWER, so the page draws the catalogue with nothing ticked.

    It is also what a user id nobody has ever registered produces, and that is deliberate: turning an
    empty answer into a 404 would buy a hand-edited URL a nicer page and cost every real request the
    statement that proved the person exists.
    """
    _world(session)

    page = viewmodels.user_roles(session, 9999)

    assert page["held"] == []
    assert [c["held"] for c in page["choices"]] == [False, False]
