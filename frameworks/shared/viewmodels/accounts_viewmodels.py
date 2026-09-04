"""accounts view models: the role catalogue with the people who hold roles, and one person's grants.

"An administrative surface with no page in the demo" is what the older net wrote next to this domain,
and the sentence describes a gap rather than a decision: every application that has roles has a
screen where somebody grants one, and this demo taught that operation in JSON only. The section
was owed, and here it is.

TWO PAGES, AND THE SECOND ONE IS SHAPED LIKE `taxonomy`'s. Granting a role is the same screen as
tagging a post — a list of everything that can be held, with what is held marked — and it is the same
pair of writes underneath: one that adds a bridge row and one that removes it. The vocabulary is
deliberately the one `taxonomy` already uses, because "open a domain and the same thing is in the
same place" is the only reason the page taxonomy is worth having.

THE PEOPLE COME FROM THE BLOG'S OWN AGGREGATE, and that is the seam working rather than a borrowing.
`blog.user_stats` is "each user with their post count", a typed aggregate this demo already computes
in ONE statement, and it is exactly the directory a roles page needs to link from. Writing a second
"list the users" read in this domain would be a second answer to a question already answered — and it
would drift, because only one of the two would ever be looked at again.

Nothing here decides anything, and nothing here writes: the three writes of this domain
(`create_role`, `assign_role`, `revoke_role`) are called by the views, which is where the demos put a
write that answers with a redirect rather than with a shape.
"""

from __future__ import annotations

from typing_extensions import TypedDict

from snakeorm import SnakeSession

from shared.usecases import accounts_usecases as usecases
from shared.usecases import blog_usecases as blog


class RoleRow(TypedDict):
    """One role in the catalogue."""

    role_id: int
    name: str


class PersonRow(TypedDict):
    """One person in the directory, with what the blog's aggregate says about them."""

    user_id: int
    username: str
    post_count: int
    comment_count: int


class RoleDirectory(TypedDict):
    """The landing page: every role, everybody who could hold one, and a refused form's reason.

    `error` is carried back rather than redirected away, for the reason every form in these demos
    gives: a redirect loses what the person typed, which is the one thing a form must not do to
    somebody it has just refused.
    """

    roles: list[RoleRow]
    role_count: int
    people: list[PersonRow]
    error: str


class GrantRow(TypedDict):
    """One role as a choice for one person: what it is, and whether they hold it."""

    role_id: int
    name: str
    held: bool


class UserRolesPage(TypedDict):
    """One person's grants: what they hold now, and every role with its state.

    `held` is a list rather than a count because the page prints the names, and `choices` carries
    every role including the held ones: a screen that only offered what was missing would have
    nowhere to put the button that takes one away.
    """

    user_id: int
    held: list[str]
    choices: list[GrantRow]


def role_directory(session: SnakeSession, *, error: str = "") -> RoleDirectory:
    """The role catalogue and the people who can hold one. TWO statements, neither per row.

    The aggregate is the blog's and it counts in the engine; the roles are this domain's. Walking
    `user.roles` here to say who holds what would be the page at one query per person, which is the
    N+1 this layer exists to keep out of a renderer — and it is why the grants live on the page
    NEXT DOOR, keyed by one user, instead of being flattened into this table.
    """
    roles: list[RoleRow] = [
        {"role_id": role.id, "name": role.name} for role in usecases.list_roles(session)
    ]
    people: list[PersonRow] = [
        {
            "user_id": row.user.id,
            "username": row.user.username,
            "post_count": row.post_count,
            "comment_count": row.comment_count,
        }
        for row in blog.user_stats(session)
    ]
    return {
        "roles": roles,
        "role_count": len(roles),
        "people": people,
        "error": error,
    }


def user_roles(session: SnakeSession, user_id: int) -> UserRolesPage:
    """Every role, with the ones this person holds marked. TWO statements, whatever the catalogue.

    No `Failure` and no probe that the user exists, which is the call the other "grants" screen in
    this demo already made: a person with no rows holds no roles, and that is an ANSWER — an empty
    list — rather than an error. Spending a statement to turn an empty answer into a 404 buys a
    hand-edited URL a nicer page and costs every real request a round trip.
    """
    held = usecases.roles_of_user(session, user_id)
    held_ids = {role.id for role in held}
    return {
        "user_id": user_id,
        "held": [role.name for role in held],
        "choices": [
            {"role_id": role.id, "name": role.name, "held": role.id in held_ids}
            for role in usecases.list_roles(session)
        ],
    }
