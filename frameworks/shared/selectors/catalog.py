"""80/20 catalog: the MOST used reads of an ORM, each one showing off ONE capability.

The idea is to have, in a single place and over the rich 26-table graph, runnable examples of what a
real backend asks for 80% of the time: get by PK, list with `include` (no N+1), filter, paginate,
count, aggregate with `group_by`, typed `annotate`, subqueries (EXISTS / IN / NOT EXISTS), navigate
deep relationships and N—N. These are PURE reads (they do not mutate); writing lives in `services`.

Each function takes a `SnakeSession` and returns typed data. Running them under the `CaptureDriver`,
the debug panel shows the SQL, the timings and the duplicates of every one of them.
"""

from __future__ import annotations

from decimal import Decimal

from snakeorm import SnakeQuery, SnakeSession, count, sum_
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.expressions import (
    SnakeDatePart,
    snake_abs,
    snake_concat,
    snake_extract,
    snake_length,
    snake_lower,
    snake_round,
    snake_trim,
    snake_upper,
)

from shared.selectors import auth_selectors, blog_selectors
from shared.models import (
    ApiToken,
    Blog,
    BlogStats,
    Comment,
    Plan,
    PlanStats,
    Post,
    PostTag,
    Sku,
    StockMovement,
    Subscription,
    User,
    UserStats,
    Visit,
)

# ---- 1) Get by PK -----------------------------------------------------------------------------


def get_user(session: SnakeSession, user_id: int) -> User | None:
    """A user by id, or `None`. The most basic case: `filter(pk) + first`.

    It delegates to the domain selector instead of repeating the query. They were written twice,
    line by line: this module is a SHOWCASE of what the ORM can do, not a second implementation of
    the domain.
    """
    return blog_selectors.get_user(session, user_id)


# ---- 2) List with include (JOIN, no N+1) ------------------------------------------------------


def list_posts_with_author(
    session: SnakeSession, *, limit: int = 20, offset: int = 0
) -> list[Post]:
    """Posts with their author AND their blog loaded in ONE query (LEFT JOIN), paginated. Zero N+1."""
    return session.all(
        SnakeQuery(Post)
        .include(Post.author, Post.blog)
        .order_by(Post.id.asc())
        .limit(limit)
        .offset(offset)
    )


# ---- 3) Filter by column ----------------------------------------------------------------------


def published_posts(session: SnakeSession) -> list[Post]:
    """Only the published posts (a filter over a bool), ordered by date descending.

    The FILTER comes from the domain fragment; what changes between this listing and `blog`'s is the
    ordering, and that is exactly what gets stacked on top. The filter used to be copied, which is
    how two queries that should be one start to drift apart.
    """
    return session.all(
        blog_selectors.published(SnakeQuery(Post)).order_by(Post.created_at.desc())
    )


def active_tokens(session: SnakeSession, user_id: int) -> list[ApiToken]:
    """A user's NON revoked tokens (compound filter: two conditions ANDed).

    The compound filter lives ONCE, in the domain selector. Here it is executed as is, without
    ordering, which is what this section of the showcase illustrates.

    (About the `== False` inside the fragment: it is mandatory, because `__eq__` on a column returns
    a `SnakeCondition` and not a `bool`. See `billing_selectors.unpaid_invoices`.)
    """
    return session.all(auth_selectors.active_of(user_id))


# ---- 4) Pagination over the VOLUME table ------------------------------------------------------


def paginate_visits(
    session: SnakeSession, *, page: int = 0, size: int = 25
) -> list[Visit]:
    """A page of visits (the big table): classic `limit`/`offset`, stable ordering by id."""
    return session.all(
        SnakeQuery(Visit).order_by(Visit.id.asc()).limit(size).offset(page * size)
    )


# ---- 5) Simple aggregates (COUNT) -------------------------------------------------------------


def count_posts(session: SnakeSession) -> int:
    """Total posts: `COUNT(*)` over a single table."""
    return session.select(SnakeQuery(Post), count())[0][0]


def count_visits(session: SnakeSession) -> int:
    """Total visits: `COUNT(*)` over the volume table."""
    return session.select(SnakeQuery(Visit), count())[0][0]


# ---- 6) typed annotate (1-hop correlated aggregates) ------------------------------------------


def user_engagement(session: SnakeSession) -> list[UserStats]:
    """Each user + their post and comment counts (two correlated aggregates, typed)."""
    return session.annotate(
        SnakeQuery(User).order_by(User.id.asc()),
        UserStats,
        post_count=User.posts.count(),
        comment_count=User.comments.count(),
    )


def blog_overview(session: SnakeSession) -> list[BlogStats]:
    """Each blog + its post and category counts (1-hop aggregates, typed)."""
    return session.annotate(
        SnakeQuery(Blog).order_by(Blog.id.asc()),
        BlogStats,
        post_count=Blog.posts.count(),
        category_count=Blog.categories.count(),
    )


def plan_adoption(session: SnakeSession) -> list[PlanStats]:
    """Each plan + its subscription count (adoption per tariff), typed."""
    return session.annotate(
        SnakeQuery(Plan).order_by(Plan.id.asc()),
        PlanStats,
        subscription_count=Plan.subscriptions.count(),
    )


# ---- 6b) Asking the engine for its PLAN ---------------------------------------------------------


def plan_for_visits_of_a_post(session: SnakeSession, post_id: int) -> list[str]:
    """The engine's plan for the filter the dashboard runs most, WITHOUT running it.

    It pairs with the advisor: `snakeorm.advisor` says which column looks unindexed by reading the
    emitted SQL, and this says what the engine intends to do about it. The advisor guesses from the
    statement; the engine answers about its own tables.

    The lines come back as each engine writes them, so this returns `list[str]` and not a shape:
    Postgres answers one column, SQLite four and MySQL a dozen.
    """
    return session.explain(SnakeQuery(Visit).filter(Visit.post_id == post_id))


# ---- 7) GROUP BY + SQL-level aggregate (tuples) -----------------------------------------------


def visits_per_post(session: SnakeSession, *, top: int = 5) -> list[tuple[int, int]]:
    """Visits per post: `GROUP BY post_id` + `COUNT(*)`. Returns the top-N (sorted in Python)."""
    rows = session.select(
        SnakeQuery(Visit).group_by(Visit.post_id), Visit.post_id, count()
    )
    return sorted(rows, key=lambda row: row[1], reverse=True)[:top]


def revenue_per_plan(session: SnakeSession) -> list[tuple[str, int | None]]:
    """Revenue per plan: JOIN to `Plan` through the relationship, `GROUP BY plan.name`,
    `SUM(price_cents)`.

    A `group_by` over a deep relationship (`Subscription.plan.name`) generates the JOIN on its own.
    It sums the price of the ACTIVE subscriptions grouping by plan name. `SUM` is `int | None` (in
    SQL an aggregate over zero rows is NULL), and the type says so — we do not lie with a bare `int`.
    """
    return session.select(
        SnakeQuery(Subscription)
        .filter(Subscription.active == True)  # noqa: E712
        .group_by(Subscription.plan.name),
        Subscription.plan.name,
        sum_(Subscription.plan.price_cents),
    )


# ---- 8) Subqueries: EXISTS / NOT EXISTS / IN --------------------------------------------------


def blogs_with_published_posts(session: SnakeSession) -> list[Blog]:
    """Blogs that have AT LEAST one published post: a correlated `WHERE EXISTS (...)`."""
    return session.all(
        SnakeQuery(Blog).filter(Blog.posts.any(Post.published == True))  # noqa: E712
    )


def users_without_subscription(session: SnakeSession) -> list[User]:
    """Users WITHOUT any subscription: `WHERE NOT (EXISTS (...))` (the `~` negates the EXISTS)."""
    return session.all(SnakeQuery(User).filter(~User.subscriptions.any()))


def posts_for_tag(session: SnakeSession, tag_id: int) -> list[Post]:
    """A tag's posts (N—N) through an IN subquery over the `PostTag` bridge.

    `as_scalar` projects the bridge's `post_id` filtered by tag; `Post.id.in_(sub)` consumes it. It
    is the portable way to resolve the N—N without materializing the join in memory.
    """
    bridged = (
        SnakeQuery(PostTag).filter(PostTag.tag_id == tag_id).as_scalar(PostTag.post_id)
    )
    return session.all(
        SnakeQuery(Post).filter(Post.id.in_(bridged)).order_by(Post.id.asc())
    )


# ---- 9) Deep navigation (nested include) ------------------------------------------------------


def recent_comments(session: SnakeSession, *, limit: int = 10) -> list[Comment]:
    """The latest comments with their post and their author loaded (two to-one in one JOIN), no N+1."""
    return session.all(
        SnakeQuery(Comment)
        .include(Comment.post, Comment.author)
        .order_by(Comment.created_at.desc())
        .limit(limit)
    )


# ---- 10) Scalar functions: text, dates, maths and JSON ----------------------------------------
#
# All of these compute IN THE ENGINE, not in Python: what comes back is already the answer. That is
# the reading the panel gives you here — one query per section, and the result of the function in
# the SQL rather than a loop over rows.


def sku_name_case(
    session: SnakeSession, *, limit: int = 8
) -> list[tuple[str, str, str, int]]:
    """`LOWER`, `UPPER` and `LENGTH` over one column.

    Split from the four below because `session.select` is typed to FOUR projected columns: the
    overloads stop at `c4`, so a fifth is not a longer tuple, it is an error. Two sections is the
    honest shape rather than reaching for something untyped.
    """
    return session.select(
        SnakeQuery(Sku).order_by(Sku.id).limit(limit),
        Sku.name,
        snake_lower(Sku.name),
        snake_upper(Sku.name),
        snake_length(Sku.name),
    )


def sku_name_edits(
    session: SnakeSession, *, limit: int = 8
) -> list[tuple[str, str, str]]:
    """`CONCAT` and `TRIM`: building a label in the engine instead of in a loop.

    `SUBSTRING` and `REPLACE` were here and came out, because `test_declarator_coverage` said so and
    it was right. Both are DECLARED out of scope for these demos with an argument attached — no page
    shows a truncated string (that is CSS's job, which knows the width) and no domain rewrites text
    on its way OUT of the database. Using them here would have been inventing a need in order to
    turn a roadmap cell green, which is the exact move that table exists to catch.
    """
    return session.select(
        SnakeQuery(Sku).order_by(Sku.id).limit(limit),
        Sku.name,
        snake_trim(Sku.name),
        snake_concat("SKU · ", Sku.name),
    )


def movements_by_date_part(
    session: SnakeSession, *, limit: int = 10
) -> tuple[list[tuple[int, int]], str | None]:
    """`EXTRACT` of year and month, or the engine's REFUSAL when it has no such function.

    Two engines out of three cannot answer this and they say so by name: SQLite has no `EXTRACT` at
    all and MySQL has no `DATE_TRUNC`. The refusal is the product here, so it comes back as data and
    the page prints it — a demo that hid it would be teaching that the ORM silently does less.
    """
    query = (
        SnakeQuery(StockMovement)
        .order_by(StockMovement.happened_at.desc())
        .limit(limit)
    )
    try:
        return (
            session.select(
                query,
                snake_extract(SnakeDatePart.YEAR, StockMovement.happened_at),
                snake_extract(SnakeDatePart.MONTH, StockMovement.happened_at),
            ),
            None,
        )
    except SnakeDialectError as refusal:
        return [], str(refusal)


def sku_magnitudes(
    session: SnakeSession, *, limit: int = 8
) -> list[tuple[str, Decimal, Decimal, int]]:
    """`ROUND` with a digit count over the price, and `ABS` over an id.

    Rounding to N digits used to be Postgres-only-broken (bug #34's open half) and the demo dodged
    it. It works on the three now, so the page shows the two-argument form: it is the one anybody
    actually reaches for.
    """
    return session.select(
        SnakeQuery(Sku).order_by(Sku.id).limit(limit),
        Sku.name,
        Sku.price,
        snake_round(Sku.price, 1),
        snake_abs(Sku.id),
    )


def sku_attributes(
    session: SnakeSession, *, limit: int = 8
) -> list[tuple[str, str, bool]]:
    """`json_get` reads a key INSIDE the JSON column, typed, without loading the document."""
    return session.select(
        SnakeQuery(Sku).order_by(Sku.id).limit(limit),
        Sku.name,
        Sku.attrs.json_get("origin", as_type=str),
        Sku.attrs.json_get("fragile", as_type=bool),
    )


def skus_matching_any_case(session: SnakeSession, term: str) -> list[Sku]:
    """`ILIKE` through the three case-insensitive helpers, OR-ed together.

    On an engine without `ILIKE` the emitter falls back to `LOWER(a) LIKE LOWER(b)`. Same rows, and
    the catalogue says so at startup rather than the query changing meaning underneath you.
    """
    return session.all(
        SnakeQuery(Sku)
        .filter(
            Sku.name.istartswith(term)
            | Sku.name.icontains(term)
            | Sku.name.iendswith(term)
        )
        .order_by(Sku.id)
    )
