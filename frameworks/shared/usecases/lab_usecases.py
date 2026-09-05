"""The LAB as SHARED functionality: every ORM experiment, written once, for all three.

Each function returns "sections" (title · teaching note · columns · rows) already JSON-able, which
both the SSR side (Flask/Django, which paint them with a generic template) and the API side (all
three, which return them as JSON) consume the same way. That way the Lab is identical on the three
frameworks without duplicating the logic: the queries come from the shared catalog
(`shared.selectors.catalog`) and from the problem showcase (`shared.showcase`).
"""

from __future__ import annotations

from typing import Any

from snakeorm import SnakeQuery, count, snake_table
from snakeorm.session import SnakeSession

from shared.models import MODELS
from shared.selectors import catalog, inventory_selectors
from shared.usecases import engagement_usecases
from shared.showcase import capture_dashboard, dashboard_page

# A section of results, JSON-able: title, note, headers and rows of primitive values.
Section = dict[str, Any]


def _section(
    title: str, note: str, columns: list[str], rows: list[list[Any]]
) -> Section:
    """Packs a section (the same shape for SSR and API)."""
    return {"title": title, "note": note, "columns": columns, "rows": rows}


def index_sections(session: SnakeSession) -> list[Section]:
    """Seeded volume: one COUNT(*) per each of the 29 tables (a lesson in reading the panel)."""
    rows = [
        [snake_table(model).name, session.select(SnakeQuery(model), count())[0][0]]
        for model in MODELS
    ]
    return [
        _section(
            "Seeded volume (COUNT per table)",
            "20 COUNT(*) queries, one per table. Open the panel: you will see all 20 and their timings.",
            ["table", "rows"],
            rows,
        )
    ]


def aggregates_sections(session: SnakeSession) -> list[Section]:
    """Aggregates: typed `annotate` (1 hop) and `GROUP BY`+`SUM` at the SQL level."""
    engagement = catalog.user_engagement(session)
    blogs = catalog.blog_overview(session)
    plans = catalog.plan_adoption(session)
    top_posts = catalog.visits_per_post(session, top=8)
    revenue = catalog.revenue_per_plan(session)
    return [
        _section(
            "Engagement per user · annotate(post_count, comment_count)",
            "Two correlated subqueries per user, typed into a UserStats. A single query.",
            ["user", "posts", "comments"],
            [
                [row.user.username, row.post_count, row.comment_count]
                for row in engagement
            ],
        ),
        _section(
            "Summary per blog · annotate(post_count, category_count)",
            "One-hop aggregates over the blog's reverse relationships.",
            ["blog", "posts", "categories"],
            [[row.blog.slug, row.post_count, row.category_count] for row in blogs],
        ),
        _section(
            "Adoption per plan · annotate(subscription_count)",
            "How many subscriptions each plan has (a correlated COUNT).",
            ["plan", "subscriptions"],
            [[row.plan.name, row.subscription_count] for row in plans],
        ),
        _section(
            "Top posts by visits · GROUP BY post_id + COUNT(*)",
            "A SQL-level aggregate over the volume table; an ordered top-8.",
            ["post_id", "visits"],
            [list(pair) for pair in top_posts],
        ),
        _section(
            "Revenue per plan · JOIN + GROUP BY plan.name + SUM(price_cents)",
            "A group_by over a deep relationship (Subscription.plan.name) generates the JOIN on its own.",
            ["plan", "revenue (cents)"],
            [[name, total] for name, total in revenue],
        ),
    ]


def subqueries_sections(session: SnakeSession) -> list[Section]:
    """Subqueries: EXISTS, NOT EXISTS and IN (over the N—N bridge)."""
    with_posts = catalog.blogs_with_published_posts(session)
    without_sub = catalog.users_without_subscription(session)
    tagged = catalog.posts_for_tag(session, 1)
    return [
        _section(
            "Blogs with at least one published post · WHERE EXISTS (...)",
            "A correlated EXISTS: it does not fetch the posts, it only asks whether any is published.",
            ["blog", "slug"],
            [[blog.title, blog.slug] for blog in with_posts],
        ),
        _section(
            "Users with NO subscription · WHERE NOT (EXISTS (...))",
            "The ~ negates the EXISTS: users with no subscription hanging off them.",
            ["user", "email"],
            [[user.username, user.email] for user in without_sub],
        ),
        _section(
            "Posts of tag #1 · Post.id IN (SELECT post_id FROM post_tags ...)",
            "It resolves the N—N with an IN subquery over the bridge, without materialising the join.",
            ["post_id", "title"],
            [[post.id, post.title] for post in tagged],
        ),
    ]


def joins_sections(session: SnakeSession) -> list[Section]:
    """Joins and include: loading relationships in ONE query (no N+1)."""
    posts = catalog.list_posts_with_author(session, limit=15)
    comments = catalog.recent_comments(session, limit=15)
    return [
        _section(
            "Posts with author and blog · include(author, blog)",
            "Two to-one relationships loaded with LEFT JOIN in ONE single query. Zero N+1.",
            ["post", "author", "blog"],
            [[post.title, post.author.username, post.blog.title] for post in posts],
        ),
        _section(
            "Recent comments with post and author · include(post, author)",
            "Navigation through two nested to-one relationships; ordered by date, in one query.",
            ["comment", "on post", "by"],
            [[c.body[:40], c.post.title[:30], c.author.username] for c in comments],
        ),
    ]


def pagination_result(
    session: SnakeSession, *, page: int = 0, size: int = 20
) -> dict[str, Any]:
    """Pagination over the VOLUME table (visits): LIMIT/OFFSET with prev/next.

    Returns the section PLUS the pagination metadata (for SSR and API alike).
    """
    page = max(0, page)
    visits = catalog.paginate_visits(session, page=page, size=size)
    section = _section(
        f"Visits · page {page + 1} (LIMIT {size} OFFSET {page * size})",
        "Classic pagination over potentially millions of rows: a stable ordering by id.",
        ["id", "post_id", "ip", "when"],
        [
            [v.id, v.post_id, v.ip, v.visited_at.isoformat(sep=" ", timespec="minutes")]
            for v in visits
        ],
    )
    return {
        "section": section,
        "page": page,
        "has_prev": page > 0,
        "has_next": len(visits) == size,
    }


def run_problems(session: SnakeSession) -> None:
    """Triggers a literal duplicate and an N+1 ON PURPOSE so the panel flags them.

    It returns nothing: the queries have to fall inside the middleware/capture scope so the panel
    counts them and points out the duplicates. The page only explains what to look for in the panel.
    """
    dashboard_page(session)


def expressions_sections(session: SnakeSession) -> list[Section]:
    """Scalar functions: the engine computes, Python only reads the answer.

    Every section here is ONE query whose result is already the value — no loop, no post-processing.
    That is the reading the panel gives you on this page: look at the SQL and the function is in it.
    """
    case = catalog.sku_name_case(session)
    edits = catalog.sku_name_edits(session)
    magnitudes = catalog.sku_magnitudes(session)
    attributes = catalog.sku_attributes(session)
    matching = catalog.skus_matching_any_case(session, "a")
    parts, refusal = catalog.movements_by_date_part(session)
    pairs = session.all(inventory_selectors.stock_for_pairs([(1, 1), (1, 2), (2, 3)]))
    sections = [
        _section(
            "Case and length · LOWER, UPPER, LENGTH",
            "Three functions over one column in a single SELECT. The engine folds; Python receives.",
            ["name", "lower", "upper", "length"],
            [list(row) for row in case],
        ),
        _section(
            "Building a label · TRIM + CONCAT",
            "CONCAT mixes a literal with a column, and ignores NULLs instead of propagating them.",
            ["name", "trimmed", "label"],
            [list(row) for row in edits],
        ),
        _section(
            "Magnitude and rounding · ABS, ROUND(x, 1)",
            "The two-argument ROUND runs on the three: PostgreSQL declares the cast its version needs.",
            ["name", "price", "rounded", "abs(id)"],
            [
                [name, str(price), str(tidy), magnitude]
                for name, price, tidy, magnitude in magnitudes
            ],
        ),
        _section(
            "Reading inside JSON · json_get(key, as_type=...)",
            "It reads ONE key out of the document, typed, without loading the rest of it.",
            ["name", "origin", "fragile"],
            [list(row) for row in attributes],
        ),
        _section(
            "Case-insensitive match · istartswith / icontains / iendswith",
            "PostgreSQL has ILIKE; the other two get LOWER(a) LIKE LOWER(b) and the catalogue says so.",
            ["id", "name"],
            [[sku.id, sku.name] for sku in matching],
        ),
        _section(
            "Named PAIRS · snake_keys(...).in_(...)",
            "(warehouse, sku) as a unit. Two separate in_() would be the cartesian product of both lists.",
            ["warehouse", "sku", "on hand"],
            [[row.warehouse_id, row.sku_id, row.on_hand] for row in pairs],
        ),
    ]
    # The refusal is a SECTION and not a swallowed exception, because on two engines out of three it
    # is the answer. SQLite has no EXTRACT and MySQL no DATE_TRUNC; the page says which and why
    # instead of showing an empty table that looks like "no rows".
    sections.append(
        _section(
            "Parts of a date · EXTRACT(year), EXTRACT(month)",
            refusal
            or "The engine pulls each component out as a number, straight from the timestamp.",
            ["year", "month"],
            [list(row) for row in parts],
        )
    )
    return sections


def plans_sections(session: SnakeSession, *, post_id: int = 1) -> list[Section]:
    """What the ENGINE says it will do, and what a request actually did.

    Two questions that look alike and are not. `EXPLAIN` asks the engine to describe a plan WITHOUT
    running it — a prediction. The report below is a recording: the statements a page really issued,
    with their timings. Reading one for the other is how a query gets optimised against the wrong
    thing.
    """
    plan = engagement_usecases.plan_for_visits_of_post(session, post_id)
    report = capture_dashboard(session)
    return [
        _section(
            f"The plan for the visits of post {post_id} · EXPLAIN",
            "The engine's own words, one line per step, and nothing was executed to get them. The "
            "three answer in different shapes — one column on PostgreSQL, four on SQLite, a dozen "
            "on MySQL — so the ORM hands back the lines rather than inventing a common row.",
            ["step"],
            [[line] for line in plan],
        ),
        _section(
            "What a dashboard request RAN · DebugReport",
            "The same recording the debug panel paints, taken here on purpose: this page provokes "
            "the dashboard's reads inside a capture scope and prints the records. A prediction and "
            "a measurement, one under the other.",
            ["#", "ms", "rows", "sql"],
            [
                [record.n, round(record.duration_ms, 2), record.rows, record.sql[:120]]
                for record in report.records
            ],
        ),
    ]
