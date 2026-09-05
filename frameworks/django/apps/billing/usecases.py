"""DUMB Django shell: re-exports the USE CASES of the billing domain, which live in `shared`.

Every use case takes a `SnakeSession` + FLAT parameters (no `request` at all), orchestrates services
and selectors, validates, commits and returns data or a framework-agnostic `Failure`. The
functionality is defined ONCE in `shared.usecases.billing_usecases` and the three frameworks share
it; here it is only re-exported so the endpoints can import from `apps.billing.usecases`.
"""

from __future__ import annotations

from shared.usecases.billing_usecases import billing_report as billing_report
from shared.usecases.billing_usecases import cancel_subscription as cancel_subscription
from shared.usecases.billing_usecases import (
    invoices_of_customer as invoices_of_customer,
    invoices_of_subscription as invoices_of_subscription,
)
from shared.usecases.billing_usecases import issue_invoice as issue_invoice
from shared.usecases.billing_usecases import list_plans as list_plans
from shared.usecases.billing_usecases import paginate_invoices as paginate_invoices
from shared.usecases.billing_usecases import pay_invoice as pay_invoice
from shared.usecases.billing_usecases import payments_of as payments_of
from shared.usecases.billing_usecases import show_invoice as show_invoice
from shared.usecases.billing_usecases import subscribe as subscribe
from shared.usecases.billing_usecases import (
    subscriptions_of_user as subscriptions_of_user,
)
from shared.usecases.billing_usecases import unpaid_invoices as unpaid_invoices
from shared.usecases.result import Failure as Failure
