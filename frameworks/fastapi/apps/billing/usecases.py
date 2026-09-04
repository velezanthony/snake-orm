"""Use cases of the billing domain: it re-exports the ASYNCHRONOUS ones from `shared.aio`.

The demo is ASGI, so this router awaits an `AsyncSession`. The synchronous twin of every function
here lives in `shared.usecases.billing_usecases` and serves the Django and Flask demos; the two are
held together by `shared/tests/test_async_mirror.py` (same names, same parameters) and
`shared/tests/test_sync_async_parity.py` (same answer, same SQL, same message).
"""

from shared.aio.billing_usecases import billing_report as billing_report
from shared.aio.billing_usecases import cancel_subscription as cancel_subscription
from shared.aio.billing_usecases import (
    invoices_of_customer as invoices_of_customer,
    invoices_of_subscription as invoices_of_subscription,
)
from shared.aio.billing_usecases import issue_invoice as issue_invoice
from shared.aio.billing_usecases import list_plans as list_plans
from shared.aio.billing_usecases import paginate_invoices as paginate_invoices
from shared.aio.billing_usecases import pay_invoice as pay_invoice
from shared.aio.billing_usecases import payments_of as payments_of
from shared.aio.billing_usecases import show_invoice as show_invoice
from shared.aio.billing_usecases import subscribe as subscribe
from shared.aio.billing_usecases import (
    subscriptions_of_user as subscriptions_of_user,
)
from shared.aio.billing_usecases import unpaid_invoices as unpaid_invoices
from shared.usecases.result import Failure as Failure
