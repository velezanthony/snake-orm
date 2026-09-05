"""80/20 catalog tests: every operation runs and returns the expected shape over real data."""

from __future__ import annotations

from snakeorm import SnakeSession
from snakeorm.debug import capture_queries

from shared.data import Scale
from shared.selectors import catalog


def test_get_user_by_pk(seeded: SnakeSession) -> None:
    """`get_user` returns the user whose id is asked for (or `None` if they do not exist)."""
    user = catalog.get_user(seeded, 1)
    assert user is not None and user.id == 1
    assert catalog.get_user(seeded, 9999) is None


def test_list_posts_with_author_has_no_n_plus_one(seeded: SnakeSession) -> None:
    """Listing posts with `include(author, blog)` resolves in ONE query (LEFT JOIN), no N+1."""
    with capture_queries() as collector:
        posts = catalog.list_posts_with_author(seeded, limit=10)
    assert posts, "the seed must have written posts"
    assert collector.report().count == 1, "include must be a single SELECT, not an N+1"


def test_counts_match_scale(seeded: SnakeSession) -> None:
    """The `COUNT(*)` aggregates match the counts of the MINIMAL scale."""
    spec = Scale.MINIMAL.spec
    assert catalog.count_posts(seeded) == spec.posts
    assert catalog.count_visits(seeded) == spec.visits


def test_annotate_returns_typed_aggregates(seeded: SnakeSession) -> None:
    """`user_engagement` returns typed `UserStats` with consistent post and comment counts."""
    stats = catalog.user_engagement(seeded)
    assert len(stats) == spec_users()
    assert sum(row.post_count for row in stats) == spec_posts()
    assert all(isinstance(row.comment_count, int) for row in stats)


def test_the_engine_hands_back_a_plan_without_running_the_query(
    seeded: SnakeSession,
) -> None:
    """`explain()` answers lines about the table, and the demo reads them like any other selector.

    One statement and no rows: what comes back is the plan, so the visit rows must not be in it.
    """
    with capture_queries() as collector:
        plan = catalog.plan_for_visits_of_a_post(seeded, 1)

    assert plan, "the engine answered no plan at all"
    assert any("visits" in line for line in plan), (
        f"the plan never mentions the table it was asked about: {plan}"
    )
    assert collector.report().count == 1, "explain must cost ONE statement, not two"


def test_group_by_and_subqueries_execute(seeded: SnakeSession) -> None:
    """The aggregate/subquery reads (group_by, EXISTS, NOT EXISTS, IN, N—N) run and return lists."""
    assert isinstance(catalog.visits_per_post(seeded, top=3), list)
    assert isinstance(catalog.revenue_per_plan(seeded), list)
    assert isinstance(catalog.blogs_with_published_posts(seeded), list)
    assert isinstance(catalog.users_without_subscription(seeded), list)
    assert isinstance(catalog.posts_for_tag(seeded, 1), list)


def spec_users() -> int:
    """User count of the MINIMAL scale (a readability helper for the test)."""
    return Scale.MINIMAL.spec.users


def spec_posts() -> int:
    """Post count of the MINIMAL scale (a readability helper for the test)."""
    return Scale.MINIMAL.spec.posts
