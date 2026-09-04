"""blog domain use cases: the complete OPERATION of each action, written once.

They orchestrate services (writes) and selectors (reads), validate and commit, and take ONLY flat
parameters —no `request`, no `HttpResponse`, nothing from a framework— returning data or an agnostic
`Failure`. The SSR view and the API endpoint are two PRESENTATIONS of the same use case: each one
parses its input, calls the use case, and translates the result into its response (redirect+flash /
JSON+status). That way the functionality lives in one place and the web is only the skin.
"""

from __future__ import annotations

from dataclasses import dataclass

from snakeorm import SnakeQuery, SnakeSession

from shared import selectors, services
from shared.models import Blog, Post, User, UserStats


def _default_blog_id(session: SnakeSession, author_id: int) -> int | None:
    """The blog a post lands in when none is given: the author's first one, or the system's first one.

    The demo's forms and endpoints do not ask for a blog; the post lands in a sensible one instead of
    demanding the data. Returns `None` only when there is NO blog at all (empty DB).
    """
    own = session.first(
        SnakeQuery(Blog).filter(Blog.owner_id == author_id).order_by(Blog.id.asc())
    )
    if own is not None:
        return own.id
    any_blog = session.first(SnakeQuery(Blog).order_by(Blog.id.asc()))
    return any_blog.id if any_blog is not None else None


@dataclass(frozen=True)
class Failure:
    """A use case that did not complete, with a framework-AGNOSTIC reason.

    The web layer maps the `reason` to its response: `missing_fields`/`taken`/`bad_credentials` →
    a form error or 400/409; `not_found` → 404; `forbidden` → 403.
    """

    reason: str


# ---- Authentication ---------------------------------------------------------------------------


def register(
    session: SnakeSession, username: str, email: str, password: str
) -> User | Failure:
    """Registers a new user: validates the fields, checks username uniqueness and commits."""
    if not (username and email and password):
        return Failure("missing_fields")
    if selectors.get_user_by_username(session, username) is not None:
        return Failure("taken")
    user = services.register_user(session, username, email, password)
    session.commit()
    return user


def login(session: SnakeSession, username: str, password: str) -> User | Failure:
    """Verifies credentials; returns the user or `Failure("bad_credentials")`."""
    user = services.authenticate(session, username, password)
    return user if user is not None else Failure("bad_credentials")


# ---- Posts: reads -----------------------------------------------------------------------------


def list_posts(session: SnakeSession) -> list[Post]:
    """Every post with its author (one query, no N+1)."""
    return selectors.list_posts(session)


def list_user_posts(session: SnakeSession, author_id: int) -> list[Post]:
    """A user's posts (for per-user views): a bounded query, without over-reading."""
    return selectors.list_user_posts(session, author_id)


def list_published(session: SnakeSession) -> list[Post]:
    """Only the published posts, ordered by title."""
    return selectors.published_posts(session)


def get_user(session: SnakeSession, user_id: int) -> User | None:
    """A user by id, or `None`. The session's own user, fetched by the one demo that has to ask.

    THE THREE DEMOS DO NOT ALL REACH THIS, and that is deliberate rather than an oversight. Django
    resolves the logged-in user in a guard and Flask in a `before_app_request` hook, both through
    `selectors.get_user` — plumbing each framework already had before this operation existed, and
    routing them through here would make the same question reachable from a PAGE in one demo and
    from none of the others. FastAPI has neither a guard nor a hook, so `/api/auth/me` asks.

    It stays SYNCHRONOUS as well as asynchronous because `shared/aio/` is the mirror of this module
    and not the other way round: a twin with no original is a mirror facing nothing, and
    `test_sync_async_parity` is what says so out loud.
    """
    return selectors.get_user(session, user_id)


def show_post(session: SnakeSession, post_id: int) -> Post | Failure:
    """A post by id, or `Failure("not_found")`."""
    post = selectors.get_post(session, post_id)
    return post if post is not None else Failure("not_found")


def editable_post(
    session: SnakeSession, post_id: int, author_id: int
) -> Post | Failure:
    """The post for the edit form: only if it exists and belongs to the author (`forbidden` otherwise)."""
    post = selectors.get_post(session, post_id)
    if post is None or post.author_id != author_id:
        return Failure("forbidden")
    return post


def user_stats(session: SnakeSession) -> list[UserStats]:
    """Each user with their post count (typed aggregate)."""
    return selectors.user_stats(session)


# ---- Posts: writes ----------------------------------------------------------------------------


def create_post(
    session: SnakeSession,
    author_id: int,
    *,
    blog_id: int | None = None,
    title: str,
    body: str,
    published: bool = False,
) -> Post | Failure:
    """Creates a post by the author inside a blog: validates the title and commits.

    `blog_id` is OPTIONAL: when not given, the post lands in the author's first blog (or the system's
    first one). That way the presentations (SSR and API of the three frameworks) do not have to ask
    for the blog; `not_found` if the DB has no blog at all.
    """
    if not title:
        return Failure("missing_fields")
    if blog_id is None:
        blog_id = _default_blog_id(session, author_id)
        if blog_id is None:
            return Failure("not_found")
    post = services.create_post(
        session, author_id, blog_id, title, body, published=published
    )
    session.commit()
    return post


def edit_post(
    session: SnakeSession,
    post_id: int,
    author_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    published: bool | None = None,
) -> Post | Failure:
    """Edits one's own post (optional fields = unchanged). `forbidden` if it does not exist or is not theirs."""
    post = services.update_post(
        session, post_id, author_id, title=title, body=body, published=published
    )
    if post is None:
        return Failure("forbidden")
    session.commit()
    return post


def remove_post(session: SnakeSession, post_id: int, author_id: int) -> Failure | None:
    """Deletes one's own post. `None` if deleted; `Failure("forbidden")` if it is gone or not theirs."""
    if not services.delete_post(session, post_id, author_id):
        return Failure("forbidden")
    session.commit()
    return None
