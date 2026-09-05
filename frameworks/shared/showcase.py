"""A "dashboard render" that exercises the ORM and, ON PURPOSE, commits two classic mistakes so the
debug panel CATCHES them and the user sees the tool earning its keep.

The panel groups by SQL TEXT and CALL SITE — not by the params — so it covers the two cases people
mix up:

- **Literal duplicate**: the SAME query (same values) runs twice because two chunks of the page ask
  for the same thing without sharing the result. It is not an N+1: it is plain repeated work.
- **N+1**: the same SQL with different params, one per parent, inside a loop.

Both traces below survive the call-site half of the key because both go through `catalog`: header and
sidebar reach the same selector line, and so does every turn of the loop.

`dashboard_page` leaves both traces mixed in with HEALTHY reads (aggregates, includes) so the report
looks like a real request. `capture_dashboard` runs it inside a capture scope and returns the
`DebugReport` ready to paint in the panel.
"""

from __future__ import annotations

from snakeorm import SnakeSession
from snakeorm.debug import DebugReport, capture_queries

from shared.selectors import catalog


def dashboard_page(session: SnakeSession) -> None:
    """Simulates painting a dashboard: some healthy reads and TWO anti-patterns planted on purpose."""
    # --- Header (healthy): current user + published posts ----------------------------------------
    catalog.get_user(session, 1)
    catalog.published_posts(session)

    # --- Body (healthy): typed aggregates and includes, no N+1 -----------------------------------
    catalog.blog_overview(session)
    catalog.user_engagement(session)
    catalog.visits_per_post(session, top=5)
    catalog.list_posts_with_author(session, limit=10)

    # --- PROBLEM 1 · LITERAL DUPLICATE -----------------------------------------------------------
    # The sidebar asks again for EXACTLY the same published posts the header already loaded. Same
    # SQL, same params: the panel flags it as a duplicate. The user's fix would be to share the
    # result between header and sidebar, not to query twice.
    catalog.published_posts(session)

    # --- PROBLEM 2 · N+1 -------------------------------------------------------------------------
    # For every user in the engagement listing, their token list is asked for in a SEPARATE query
    # (same SQL, different param). The textbook N+1: it should be solved with an include/prefetch,
    # not in a loop.
    for user_stat in catalog.user_engagement(session):
        catalog.active_tokens(session, user_stat.user.id)


def capture_dashboard(session: SnakeSession) -> DebugReport:
    """Runs `dashboard_page` under a capture scope and returns the report (for the panel/tests)."""
    with capture_queries() as collector:
        dashboard_page(session)
    return collector.report()
