"""Use cases of the engagement domain: it re-exports the ASYNCHRONOUS ones from `shared.aio`.

The demo is ASGI, so this router awaits an `AsyncSession`. The synchronous twin of every function
here lives in `shared.usecases.engagement_usecases` and serves the Django and Flask demos; the two are
held together by `shared/tests/test_async_mirror.py` (same names, same parameters) and
`shared/tests/test_sync_async_parity.py` (same answer, same SQL, same message).
"""

from shared.aio.engagement_usecases import add_comment as add_comment
from shared.aio.engagement_usecases import add_reaction as add_reaction
from shared.aio.engagement_usecases import comments_of_post as comments_of_post
from shared.aio.engagement_usecases import reactions_of_post as reactions_of_post
from shared.aio.engagement_usecases import record_visit as record_visit
from shared.aio.engagement_usecases import visits_of_post as visits_of_post
from shared.usecases.result import Failure as Failure
from shared.aio.engagement_usecases import stream_visits as stream_visits
