"""DUMB Django shell: re-exports the domain's SELECTORS (reads), which live in `shared`.

Every selector takes a `SnakeSession` and returns data without mutating it. The logic is defined ONCE
in `shared.selectors.blog_selectors` and is shared across the three frameworks; here it is only
re-exported so views import from `apps.blog.selectors` (their layer), not from `shared` directly.
"""

from __future__ import annotations

from shared.selectors.blog_selectors import get_post as get_post
from shared.selectors.blog_selectors import get_user as get_user
from shared.selectors.blog_selectors import get_user_by_username as get_user_by_username
from shared.selectors.blog_selectors import list_posts as list_posts
from shared.selectors.blog_selectors import list_user_posts as list_user_posts
from shared.selectors.blog_selectors import published_posts as published_posts
from shared.selectors.blog_selectors import user_stats as user_stats
