"""View models of the billing domain: it re-exports those of `shared.viewmodels` (they live once).

The same seam the other apps of this demo already have, and it exists for the same reason: a view
imports from ITS OWN layer, so the day the shared package moves, one line here changes instead of
one line in every view. The `X as X` form is not decoration either — it is what tells a type checker
the name is deliberately part of this module's public surface rather than an import somebody forgot
to use.

There is no `usecases` re-export beside these for the write side, because this domain HAS no write
side. Billing offers three pages — list, detail and report — and the absence of a create, an update
and a delete is the domain's statement rather than a gap: an invoice is raised by an operation and
settled by another, never retyped into a form.
"""

from shared.viewmodels.billing_viewmodels import BillingReportPage as BillingReportPage
from shared.viewmodels.billing_viewmodels import InvoiceDetailPage as InvoiceDetailPage
from shared.viewmodels.billing_viewmodels import InvoiceListPage as InvoiceListPage
from shared.viewmodels.billing_viewmodels import InvoiceRow as InvoiceRow
from shared.viewmodels.billing_viewmodels import PaidOption as PaidOption
from shared.viewmodels.billing_viewmodels import PaymentRow as PaymentRow
from shared.viewmodels.billing_viewmodels import PlanRevenueRow as PlanRevenueRow
from shared.viewmodels.billing_viewmodels import PlanStatsRow as PlanStatsRow
from shared.viewmodels.billing_viewmodels import billing_report as billing_report
from shared.viewmodels.billing_viewmodels import invoice_detail as invoice_detail
from shared.viewmodels.billing_viewmodels import invoice_list as invoice_list
from shared.viewmodels.billing_viewmodels import money_from_cents as money_from_cents
from shared.viewmodels.billing_viewmodels import parse_paid as parse_paid
