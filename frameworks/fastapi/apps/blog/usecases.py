"""Use cases of the blog domain: it re-exports the ASYNCHRONOUS ones from `shared.aio`.

The demo is ASGI, so this router awaits an `AsyncSession`. The synchronous twin of every function
here lives in `shared.usecases.blog_usecases` and serves the Django and Flask demos; the two are
held together by `shared/tests/test_async_mirror.py` (same names, same parameters) and
`shared/tests/test_sync_async_parity.py` (same answer, same SQL, same message). `Failure` is
imported from the SYNCHRONOUS module on purpose: blog declares its own `Failure` class rather than
the `shared.usecases.result.Failure` the other five domains share, and the asynchronous twin reuses
that same class instead of a second one with the same shape, so this router's `isinstance` checks
keep working unchanged.
"""

from shared.aio.blog_usecases import create_post as create_post
from shared.aio.blog_usecases import edit_post as edit_post
from shared.aio.blog_usecases import editable_post as editable_post
from shared.aio.blog_usecases import get_user as get_user
from shared.aio.blog_usecases import list_posts as list_posts
from shared.aio.blog_usecases import list_published as list_published
from shared.aio.blog_usecases import list_user_posts as list_user_posts
from shared.aio.blog_usecases import login as login
from shared.aio.blog_usecases import register as register
from shared.aio.blog_usecases import remove_post as remove_post
from shared.aio.blog_usecases import show_post as show_post
from shared.aio.blog_usecases import user_stats as user_stats
from shared.usecases.blog_usecases import Failure as Failure
