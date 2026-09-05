"""Use cases of the auth domain: it re-exports the ASYNCHRONOUS ones from `shared.aio`.

The demo is ASGI, so this router awaits an `AsyncSession`. The synchronous twin of every function
here lives in `shared.usecases.auth_usecases` and serves the Django and Flask demos; the two are
held together by `shared/tests/test_async_mirror.py` (same names, same parameters) and
`shared/tests/test_sync_async_parity.py` (same answer, same SQL, same message).
"""

from shared.aio.auth_usecases import active_tokens as active_tokens
from shared.aio.auth_usecases import issue_token as issue_token
from shared.aio.auth_usecases import revoke_token as revoke_token
from shared.aio.auth_usecases import sessions_of_user as sessions_of_user
from shared.aio.auth_usecases import tokens_of_user as tokens_of_user
from shared.usecases.result import Failure as Failure
