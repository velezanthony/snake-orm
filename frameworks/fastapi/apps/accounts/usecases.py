"""Use cases of the accounts domain: it re-exports the ASYNCHRONOUS ones from `shared.aio`.

The demo is ASGI, so this router awaits an `AsyncSession`. The synchronous twin of every function
here lives in `shared.usecases.accounts_usecases` and serves the Django and Flask demos; the two are
held together by `shared/tests/test_async_mirror.py` (same names, same parameters) and
`shared/tests/test_sync_async_parity.py` (same answer, same SQL, same message).
"""

from shared.aio.accounts_usecases import assign_role as assign_role
from shared.aio.accounts_usecases import create_role as create_role
from shared.aio.accounts_usecases import list_roles as list_roles
from shared.aio.accounts_usecases import revoke_role as revoke_role
from shared.aio.accounts_usecases import roles_of_user as roles_of_user
from shared.usecases.result import Failure as Failure
