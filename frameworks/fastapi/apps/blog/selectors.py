"""DUMB re-export of the blog domain's SELECTORS (reads) (they live in `shared`).

The queries are defined ONCE in `shared.selectors.blog_selectors`; the shell only re-exposes them.
"""

from shared.selectors.blog_selectors import get_post as get_post
from shared.selectors.blog_selectors import get_user as get_user
from shared.selectors.blog_selectors import get_user_by_username as get_user_by_username
from shared.selectors.blog_selectors import list_posts as list_posts
from shared.selectors.blog_selectors import list_user_posts as list_user_posts
from shared.selectors.blog_selectors import published_posts as published_posts
from shared.selectors.blog_selectors import user_stats as user_stats
