"""DUMB Django shell: re-exports the domain's USE CASES, which live in `shared`.

Every use case takes a `SnakeSession` + FLAT parameters (no `request` at all), orchestrates services
and selectors, validates, commits and returns data or a framework-agnostic `Failure`. The
functionality is defined ONCE in `shared.usecases.blog_usecases` and the three frameworks share it;
here it is only re-exported so views import from `apps.blog.usecases` (their layer), not from
`shared` directly.
"""

from __future__ import annotations

from shared.usecases.blog_usecases import Failure as Failure
from shared.usecases.blog_usecases import create_post as create_post
from shared.usecases.blog_usecases import edit_post as edit_post
from shared.usecases.blog_usecases import editable_post as editable_post
from shared.usecases.blog_usecases import list_posts as list_posts
from shared.usecases.blog_usecases import list_published as list_published
from shared.usecases.blog_usecases import list_user_posts as list_user_posts
from shared.usecases.blog_usecases import login as login
from shared.usecases.blog_usecases import register as register
from shared.usecases.blog_usecases import remove_post as remove_post
from shared.usecases.blog_usecases import show_post as show_post
from shared.usecases.blog_usecases import user_stats as user_stats
