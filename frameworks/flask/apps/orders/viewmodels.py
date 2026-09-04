"""View models of the orders domain: it re-exports those of `shared.viewmodels` (they live once).

Presentation-ready flat dicts, one function per page of the taxonomy. The views import from HERE and
never from `shared` directly, which is the same rule the selectors and use cases next door follow:
the demo is a wrapper, and a wrapper that reaches around itself stops showing where its own layers
are.

`CsvExport` is here too and it is not a page: it is the SHAPE the export hands the web layer — a
filename, a header and a LAZY generator of rows. The view needs the type to write the response,
and reaching into `shared` for it while every sibling comes from here is the leak this module
exists to close. `LINE_EXPORT_HEADER` travels with it so that nothing has to retype its eleven
column names — a second spelling of them is the drift this layer was put in front of.

`parse_state` is re-exported alongside the page builders even though it renders nothing, and that is
the point of having it: without it each demo writes its own `try/except ValueError` around
`OrderState(...)`, and the two then disagree about what an unrecognised `?state=` means.
"""

from shared.viewmodels.orders_viewmodels import (
    LINE_EXPORT_HEADER as LINE_EXPORT_HEADER,
)
from shared.viewmodels.orders_viewmodels import CsvExport as CsvExport
from shared.viewmodels.orders_viewmodels import CustomerOption as CustomerOption
from shared.viewmodels.orders_viewmodels import CustomerStatsRow as CustomerStatsRow
from shared.viewmodels.orders_viewmodels import HighlightRow as HighlightRow
from shared.viewmodels.orders_viewmodels import InvoiceInfo as InvoiceInfo
from shared.viewmodels.orders_viewmodels import OperationLineRow as OperationLineRow
from shared.viewmodels.orders_viewmodels import OrderDeletePage as OrderDeletePage
from shared.viewmodels.orders_viewmodels import OrderDetailPage as OrderDetailPage
from shared.viewmodels.orders_viewmodels import OrderFormPage as OrderFormPage
from shared.viewmodels.orders_viewmodels import OrderLineRow as OrderLineRow
from shared.viewmodels.orders_viewmodels import OrderListPage as OrderListPage
from shared.viewmodels.orders_viewmodels import (
    OrderOperationPage as OrderOperationPage,
)
from shared.viewmodels.orders_viewmodels import OrderReportPage as OrderReportPage
from shared.viewmodels.orders_viewmodels import OrderRow as OrderRow
from shared.viewmodels.orders_viewmodels import (
    RepeatCustomerRow as RepeatCustomerRow,
)
from shared.viewmodels.orders_viewmodels import SequenceRow as SequenceRow
from shared.viewmodels.orders_viewmodels import StateOption as StateOption
from shared.viewmodels.orders_viewmodels import StateTotalRow as StateTotalRow
from shared.viewmodels.orders_viewmodels import (
    SubscriptionOption as SubscriptionOption,
)
from shared.viewmodels.orders_viewmodels import (
    order_delete_confirm as order_delete_confirm,
)
from shared.viewmodels.orders_viewmodels import order_detail as order_detail
from shared.viewmodels.orders_viewmodels import order_form as order_form
from shared.viewmodels.orders_viewmodels import (
    order_lines_export as order_lines_export,
)
from shared.viewmodels.orders_viewmodels import order_list as order_list
from shared.viewmodels.orders_viewmodels import order_operation as order_operation
from shared.viewmodels.orders_viewmodels import order_report as order_report
from shared.viewmodels.orders_viewmodels import parse_state as parse_state
from shared.viewmodels.orders_viewmodels import state_label as state_label
from shared.viewmodels.orders_viewmodels import customer_sheet as customer_sheet
