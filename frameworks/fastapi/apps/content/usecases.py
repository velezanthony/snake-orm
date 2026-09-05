"""Use cases of the content domain: it re-exports the ASYNCHRONOUS ones from `shared.aio`.

The demo is ASGI, so this router awaits an `AsyncSession`. The synchronous twin of every function
here lives in `shared.usecases.content_usecases` and serves the Django and Flask demos; the two are
held together by `shared/tests/test_async_mirror.py` (same names, same parameters) and
`shared/tests/test_sync_async_parity.py` (same answer, same SQL, same message).
"""

from shared.aio.content_usecases import add_revision as add_revision
from shared.aio.content_usecases import attach_file as attach_file
from shared.aio.content_usecases import attachments_of_post as attachments_of_post
from shared.aio.content_usecases import remove_attachment as remove_attachment
from shared.aio.content_usecases import revisions_of_post as revisions_of_post
from shared.usecases.result import Failure as Failure
from shared.aio.content_usecases import revision_timeline as revision_timeline
