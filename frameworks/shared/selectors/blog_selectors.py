"""blog domain — SELECTORS: pure reads (queries that return data, without mutating).

They take a `SnakeSession` and return models. This is the READ logic used by the CRUD pages of the
three demos (each framework re-exports it from its `apps/blog/selectors.py`). For the showcase of
complex queries (aggregates, subqueries, N—N) look at `shared.selectors.catalog`.

Every read here comes in TWO pieces, and the split is the seam the asynchronous demo stands on. The
FRAGMENT builds a `SnakeQuery` (or, for `annotate`, the query PLUS the aggregate mapping it projects)
and does not run it; the EXECUTOR takes a session and runs it. Only the executor has a colour —
`session.all(...)` on one path, `await session.all(...)` on the other — so the SQL, which is the part
that drifts when it is written twice, is written once. `shared.services.blog_services` also reuses
`post_by_id` and `user_by_username` for its own look-ups, for the same reason. See
`shared/aio/blog_usecases.py` for the other half.
"""

from __future__ import annotations

from snakeorm import SnakeQuery, SnakeSession, SnakeValue

from shared.models import Post, User, UserStats


def posts_query() -> SnakeQuery[Post]:
    """FRAGMENT: every post with its author and its blog loaded, ordered by id. NOT executed."""
    return SnakeQuery(Post).include(Post.author, Post.blog).order_by(Post.id.asc())


def list_posts(session: SnakeSession) -> list[Post]:
    """Every post with its author and its blog loaded (one JOIN, no N+1)."""
    return session.all(posts_query())


def user_posts_query(user_id: int) -> SnakeQuery[Post]:
    """FRAGMENT: a user's posts, with their author and their blog loaded. NOT executed."""
    return (
        SnakeQuery(Post)
        .filter(Post.author_id == user_id)
        .include(Post.author, Post.blog)
        .order_by(Post.id.asc())
    )


def list_user_posts(session: SnakeSession, user_id: int) -> list[Post]:
    """A user's posts, with their author and their blog loaded."""
    return session.all(user_posts_query(user_id))


def post_by_id(post_id: int) -> SnakeQuery[Post]:
    """FRAGMENT: one post by id, with its author and its blog loaded. NOT executed.

    `shared.services.blog_services` reuses this for the ownership look-up an edit or a delete needs
    before it writes, and the asynchronous twin of those writes reuses it too — so both colours, and
    both the read and the write path, resolve "the post with this id" through the exact same `WHERE`.
    """
    return SnakeQuery(Post).filter(Post.id == post_id).include(Post.author, Post.blog)


def get_post(session: SnakeSession, post_id: int) -> Post | None:
    """A post by id (with its author and its blog), or `None` if it does not exist."""
    return session.first(post_by_id(post_id))


def published(query: SnakeQuery[Post]) -> SnakeQuery[Post]:
    """FRAGMENT: keeps only the published posts. Takes a query and returns another one.

    This is the composable shape, and it needs no new ORM machinery: `filter()` already returns a
    `SnakeQuery[Post]`, so one fragment stacks onto another and the type survives whole.

    It exists because the same filter was written twice —here and in `catalog`— with a different
    ordering, which is how two queries that should be one start to drift apart.

    `== True` is not a style slip: `__eq__` on a column returns a `SnakeCondition`, not a `bool`, so
    `filter(Post.published)` would not compile.
    """
    return query.filter(Post.published == True)  # noqa: E712


def published_posts(session: SnakeSession) -> list[Post]:
    """Only the published ones, ordered by title."""
    return session.all(published(SnakeQuery(Post)).order_by(Post.title.asc()))


def user_by_id(user_id: int) -> SnakeQuery[User]:
    """FRAGMENT: one user by id. NOT executed."""
    return SnakeQuery(User).filter(User.id == user_id)


def get_user(session: SnakeSession, user_id: int) -> User | None:
    """A user by id, or `None`."""
    return session.first(user_by_id(user_id))


def user_by_username(username: str) -> SnakeQuery[User]:
    """FRAGMENT: one user by username (the login look-up). NOT executed.

    `shared.services.blog_services.authenticate` reuses this to find the row it checks the password
    against, and the asynchronous twin's `register`/`login` reuse it too — so the uniqueness check, the
    password check and both colours run the exact same `WHERE username = ...` rather than agreeing on
    it by convention across call sites.
    """
    return SnakeQuery(User).filter(User.username == username)


def get_user_by_username(session: SnakeSession, username: str) -> User | None:
    """A user by username (for the login), or `None`."""
    return session.first(user_by_username(username))


def user_stats_query() -> SnakeQuery[User]:
    """FRAGMENT: every user by id, NOT executed — `annotate` stacks the aggregates on top."""
    return SnakeQuery(User).order_by(User.id.asc())


def user_stats_aggregates() -> dict[str, SnakeValue[int]]:
    """FRAGMENT: the aggregate mapping `user_stats` annotates onto `UserStats`.

    `annotate` takes its aggregates as `**kwargs`, so the shared half of this read is a dict, the
    same rule `billing_selectors.plan_stats_aggregates` follows: the expression is written ONCE, and
    both colours consume the same object instead of two `User.posts.count()` calls that could drift.
    """
    return {
        "post_count": User.posts.count(),
        "comment_count": User.comments.count(),
    }


def user_stats(session: SnakeSession) -> list[UserStats]:
    """Each user with their post and comment counts (correlated aggregates over the inverse sides)."""
    return session.annotate(user_stats_query(), UserStats, **user_stats_aggregates())
