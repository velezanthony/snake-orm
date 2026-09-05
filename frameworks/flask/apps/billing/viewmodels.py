"""View models of the billing domain: it re-exports those of `shared.viewmodels` (they live once).

Presentation-ready flat dicts, one function per page. The views import from HERE and never from
`shared` directly, which is the rule the selectors and use cases next door already follow: the demo
is a wrapper, and a wrapper that reaches around itself stops showing where its own layers are.

THREE page builders and no more, because billing has three pages. There is no `billing_form` and no
`billing_delete_confirm` to re-export, and the gap is the domain's whole statement: an invoice is
raised by an operation and settled by another, never retyped into a form.

`parse_paid` travels with them even though it renders nothing, for the same reason `parse_state`
does one domain over: without it each demo writes its own reading of `?paid=`, and the two then
disagree about what `paid=maybe` means — one filtering nothing, the other raising on a URL somebody
hand-edited.
"""

from shared.viewmodels.billing_viewmodels import (
    BillingReportPage as BillingReportPage,
)
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
from shared.viewmodels.billing_viewmodels import paid_label as paid_label
from shared.viewmodels.billing_viewmodels import parse_paid as parse_paid
