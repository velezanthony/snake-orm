"""View models of the orders domain: it re-exports those of `shared.viewmodels` (they live once).

Same seam as the other four modules of this app, and it is the one that matters most here: the
module it re-exports opens with the rule that a view model must never run on the way to an
operation. Importing it through this file is what keeps a view importing from its own layer, so the
day that rule grows a second line there is one import to follow rather than a search.
"""

from shared.viewmodels.orders_viewmodels import CustomerOption as CustomerOption
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
from shared.viewmodels.orders_viewmodels import OrderRow as OrderRow
from shared.viewmodels.orders_viewmodels import StateOption as StateOption
from shared.viewmodels.orders_viewmodels import (
    SubscriptionOption as SubscriptionOption,
)
from shared.viewmodels.orders_viewmodels import (
    order_delete_confirm as order_delete_confirm,
)
from shared.viewmodels.orders_viewmodels import order_detail as order_detail
from shared.viewmodels.orders_viewmodels import order_form as order_form
from shared.viewmodels.orders_viewmodels import order_list as order_list
from shared.viewmodels.orders_viewmodels import order_operation as order_operation
from shared.viewmodels.orders_viewmodels import parse_state as parse_state
from shared.viewmodels.orders_viewmodels import state_label as state_label
from shared.viewmodels.orders_viewmodels import CsvExport as CsvExport
from shared.viewmodels.orders_viewmodels import CustomerStatsRow as CustomerStatsRow
from shared.viewmodels.orders_viewmodels import HighlightRow as HighlightRow
from shared.viewmodels.orders_viewmodels import OrderReportPage as OrderReportPage
from shared.viewmodels.orders_viewmodels import RepeatCustomerRow as RepeatCustomerRow
from shared.viewmodels.orders_viewmodels import SequenceRow as SequenceRow
from shared.viewmodels.orders_viewmodels import StateTotalRow as StateTotalRow
from shared.viewmodels.orders_viewmodels import (
    order_lines_export as order_lines_export,
)
from shared.viewmodels.orders_viewmodels import order_report as order_report
from shared.viewmodels.orders_viewmodels import customer_sheet as customer_sheet
