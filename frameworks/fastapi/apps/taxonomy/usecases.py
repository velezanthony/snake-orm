"""Use cases of the taxonomy domain: it re-exports the ASYNCHRONOUS ones from `shared.aio`.

The demo is ASGI, so this router awaits an `AsyncSession`. The synchronous twin of every function
here lives in `shared.usecases.taxonomy_usecases` and serves the Django and Flask demos; the two are
held together by `shared/tests/test_async_mirror.py` (same names, same parameters) and
`shared/tests/test_sync_async_parity.py` (same answer, same SQL, same message).
"""

from shared.aio.taxonomy_usecases import create_tag as create_tag
from shared.aio.taxonomy_usecases import list_groups as list_groups
from shared.aio.taxonomy_usecases import list_tags as list_tags
from shared.aio.taxonomy_usecases import (
    posts_with_every_tag as posts_with_every_tag,
)
from shared.aio.taxonomy_usecases import (
    posts_with_tag_but_not as posts_with_tag_but_not,
)
from shared.aio.taxonomy_usecases import tag_post as tag_post
from shared.aio.taxonomy_usecases import tags_of_post as tags_of_post
from shared.aio.taxonomy_usecases import untag_post as untag_post
from shared.usecases.result import Failure as Failure
from shared.aio.taxonomy_usecases import tag_breadcrumb as tag_breadcrumb
from shared.aio.taxonomy_usecases import tag_descendants as tag_descendants
