"""blog domain (authentication, posts), asked of an `AsyncSession`. The twin of
`shared/usecases/blog_usecases.py`.

Same names, same parameters, same answers — including the same `Failure` reasons, because a reason
is what the user reads and two wordings of one refusal is the drift this package's nets exist to
catch. What differs is one keyword per statement.

The queries are NOT rebuilt here: `posts_query`, `user_posts_query`, `post_by_id`, `published`,
`user_by_id`, `user_by_username`, `user_stats_query` and `user_stats_aggregates` come from the
synchronous selectors, unchanged, because a `SnakeQuery` has no colour. The ownership rule is not
retyped either: `is_owner` comes from the synchronous services module, a pure predicate that touches
no session, so both `edit_post` and `remove_post` below enforce the identical rule `update_post`/
`delete_post` enforce on the other colour.

ON `Failure`: this domain is the ONE exception among the six served here. Every other twinned domain
returns `shared.usecases.result.Failure`, a single class shared by all of them; `blog_usecases.py`
instead declares its OWN `Failure` dataclass, because the blog router (`apps/blog/urls.py`) was built
against THAT class and does `isinstance(result, Failure)` to decide when to raise. This module
reuses that SAME class — imported, not redeclared — rather than defining a second one with the same
shape: two `Failure` classes in one domain would make `isinstance` a coin flip depending on which
module's `Failure` the caller imported, exactly the kind of two-of-a-kind-drift this package exists
to prevent inside the CONTROL FLOW it necessarily duplicates.
"""

from __future__ import annotations

from snakeorm import AsyncSession, SnakeQuery

from shared.auth import hash_password, verify_password
from shared.models import Blog, Post, User, UserStats
from shared.selectors.blog_selectors import (
    post_by_id,
    user_by_id,
    posts_query,
    published,
    user_by_username,
    user_posts_query,
    user_stats_aggregates,
    user_stats_query,
)
from shared.services.blog_services import is_owner
from shared.usecases.blog_usecases import Failure


async def _default_blog_id(session: AsyncSession, author_id: int) -> int | None:
    """The blog a post lands in when none is given: the author's first one, or the system's first one.

    The asynchronous twin of `shared.usecases.blog_usecases._default_blog_id`: same two look-ups, one
    `await` each. It stays private (leading underscore) for the same reason the synchronous one does —
    `shared/tests/test_async_mirror.py` only compares PUBLIC use cases, and this is plumbing for one
    of them, not a use case of its own.
    """
    own = await session.first(
        SnakeQuery(Blog).filter(Blog.owner_id == author_id).order_by(Blog.id.asc())
    )
    if own is not None:
        return own.id
    any_blog = await session.first(SnakeQuery(Blog).order_by(Blog.id.asc()))
    return any_blog.id if any_blog is not None else None


# ---- Authentication ---------------------------------------------------------------------------


async def register(
    session: AsyncSession, username: str, email: str, password: str
) -> User | Failure:
    """Registers a new user: validates the fields, checks username uniqueness and commits."""
    if not (username and email and password):
        return Failure("missing_fields")
    if await session.first(user_by_username(username)) is not None:
        return Failure("taken")
    user = await session.add(
        User(username=username, email=email, password_hash=hash_password(password))
    )
    await session.commit()
    return user


async def login(session: AsyncSession, username: str, password: str) -> User | Failure:
    """Verifies credentials; returns the user or `Failure("bad_credentials")`."""
    user = await session.first(user_by_username(username))
    if user is not None and verify_password(password, user.password_hash):
        return user
    return Failure("bad_credentials")


# ---- Posts: reads -----------------------------------------------------------------------------


async def list_posts(session: AsyncSession) -> list[Post]:
    """Every post with its author (one query, no N+1)."""
    return await session.all(posts_query())


async def list_user_posts(session: AsyncSession, author_id: int) -> list[Post]:
    """A user's posts (for per-user views): a bounded query, without over-reading."""
    return await session.all(user_posts_query(author_id))


async def list_published(session: AsyncSession) -> list[Post]:
    """Only the published posts, ordered by title."""
    return await session.all(published(SnakeQuery(Post)).order_by(Post.title.asc()))


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    """A user by id, or `None`. The async twin of `blog_selectors.get_user`.

    Both sit on the SAME fragment — `user_by_id` builds a query and executes nothing — which is the
    seam this whole layer rests on: the SQL has no colour, so only the awaiting differs.
    """
    return await session.first(user_by_id(user_id))


async def show_post(session: AsyncSession, post_id: int) -> Post | Failure:
    """A post by id, or `Failure("not_found")`."""
    post = await session.first(post_by_id(post_id))
    return post if post is not None else Failure("not_found")


async def editable_post(
    session: AsyncSession, post_id: int, author_id: int
) -> Post | Failure:
    """The post for the edit form: only if it exists and belongs to the author (`forbidden` otherwise)."""
    post = await session.first(post_by_id(post_id))
    if post is None or not is_owner(post, author_id):
        return Failure("forbidden")
    return post


async def user_stats(session: AsyncSession) -> list[UserStats]:
    """Each user with their post count (typed aggregate)."""
    return await session.annotate(
        user_stats_query(), UserStats, **user_stats_aggregates()
    )


# ---- Posts: writes ----------------------------------------------------------------------------


async def create_post(
    session: AsyncSession,
    author_id: int,
    *,
    blog_id: int | None = None,
    title: str,
    body: str,
    published: bool = False,
) -> Post | Failure:
    """Creates a post by the author inside a blog: validates the title and commits.

    `blog_id` is OPTIONAL: when not given, the post lands in the author's first blog (or the system's
    first one), through `_default_blog_id`, the same two-step look-up the synchronous side runs;
    `not_found` if the DB has no blog at all.
    """
    if not title:
        return Failure("missing_fields")
    if blog_id is None:
        blog_id = await _default_blog_id(session, author_id)
        if blog_id is None:
            return Failure("not_found")
    post = await session.add(
        Post(
            title=title,
            body=body,
            published=published,
            blog_id=blog_id,
            category_id=None,
            author_id=author_id,
        )
    )
    await session.commit()
    return post


async def edit_post(
    session: AsyncSession,
    post_id: int,
    author_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    published: bool | None = None,
) -> Post | Failure:
    """Edits one's own post (optional fields = unchanged). `forbidden` if it does not exist or is not theirs."""
    post = await session.first(post_by_id(post_id))
    if post is None or not is_owner(post, author_id):
        return Failure("forbidden")
    if title is not None:
        post.title = title
    if body is not None:
        post.body = body
    if published is not None:
        post.published = published
    await session.update(post)
    await session.commit()
    return post


async def remove_post(
    session: AsyncSession, post_id: int, author_id: int
) -> Failure | None:
    """Deletes one's own post. `None` if deleted; `Failure("forbidden")` if it is gone or not theirs."""
    post = await session.first(post_by_id(post_id))
    if post is None or not is_owner(post, author_id):
        return Failure("forbidden")
    await session.delete(post)
    await session.commit()
    return None
