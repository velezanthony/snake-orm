"""blog domain — SERVICES: writes and rules (create, authenticate, update, delete).

They take a `SnakeSession` and MUTATE the state (or validate it). This is the domain's WRITE logic,
defined once and reused by the three frameworks. Post ownership (only its author edits or deletes it)
is checked here, not in every framework.

`is_owner` is a PURE predicate — it takes a `Post` and an author id, touches no session — precisely
so the asynchronous twin (`shared/aio/blog_usecases.py`) can enforce the exact same rule without a
session of its own. `update_post` and `delete_post` below already look up the post through an
`AsyncSession`-flavoured `await session.first(...)` on the other colour, so the only place left where
the two paths could disagree is the comparison itself; a `bool` has no colour, so importing it removes
the disagreement rather than merely documenting it.
"""

from __future__ import annotations

from snakeorm import SnakeSession

from shared.auth import hash_password, verify_password
from shared.models import Post, User
from shared.selectors.blog_selectors import get_post, get_user_by_username


def register_user(
    session: SnakeSession, username: str, email: str, password: str
) -> User:
    """Creates a user with the password hashed. Username/email uniqueness is enforced by the DB."""
    return session.add(
        User(username=username, email=email, password_hash=hash_password(password))
    )


def authenticate(session: SnakeSession, username: str, password: str) -> User | None:
    """Returns the user if the password matches; `None` if they do not exist or it does not match."""
    user = get_user_by_username(session, username)
    if user is not None and verify_password(password, user.password_hash):
        return user
    return None


def is_owner(post: Post, author_id: int) -> bool:
    """Whether `author_id` is the one person allowed to edit or delete `post`.

    A pure predicate — no session, no query — is the only shape that both `update_post`/`delete_post`
    below AND their asynchronous twin can call identically: the twin already has its OWN `await
    session.first(...)` for the look-up (a `SnakeSession` and an `AsyncSession` cannot share a call),
    but the RULE applied to what that look-up returns is one function, imported, not one `if` written
    twice with the same condition and a silent chance of it stopping being the same condition.
    """
    return post.author_id == author_id


def create_post(
    session: SnakeSession,
    author_id: int,
    blog_id: int,
    title: str,
    body: str,
    *,
    published: bool = False,
) -> Post:
    """Creates a post by the given author inside a blog. The category is optional (here, none)."""
    return session.add(
        Post(
            title=title,
            body=body,
            published=published,
            blog_id=blog_id,
            category_id=None,
            author_id=author_id,
        )
    )


def update_post(
    session: SnakeSession,
    post_id: int,
    author_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    published: bool | None = None,
) -> Post | None:
    """Updates a post ONLY if it belongs to the author. `None` if it does not exist or is not theirs."""
    post = get_post(session, post_id)
    if post is None or not is_owner(post, author_id):
        return None
    if title is not None:
        post.title = title
    if body is not None:
        post.body = body
    if published is not None:
        post.published = published
    session.update(post)
    return post


def delete_post(session: SnakeSession, post_id: int, author_id: int) -> bool:
    """Deletes a post ONLY if it belongs to the author. `False` if it does not exist or is not theirs."""
    post = get_post(session, post_id)
    if post is None or not is_owner(post, author_id):
        return False
    session.delete(post)
    return True
