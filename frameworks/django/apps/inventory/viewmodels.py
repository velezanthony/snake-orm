"""View models of the inventory domain: it re-exports those of `shared.viewmodels` (they live once).

The re-export is the same seam the other four modules of this app already are, and it exists for the
same reason: a view imports from ITS OWN layer, so the day the shared package moves, one line here
changes instead of one line in every view. The `X as X` form is not decoration either — it is what
tells a type checker the name is deliberately part of this module's public surface rather than an
import somebody forgot to use.
"""

from shared.viewmodels.inventory_viewmodels import MovementRow as MovementRow
from shared.viewmodels.inventory_viewmodels import SkuOption as SkuOption
from shared.viewmodels.inventory_viewmodels import StockDeletePage as StockDeletePage
from shared.viewmodels.inventory_viewmodels import StockDetailPage as StockDetailPage
from shared.viewmodels.inventory_viewmodels import StockFormPage as StockFormPage
from shared.viewmodels.inventory_viewmodels import StockListPage as StockListPage
from shared.viewmodels.inventory_viewmodels import StockRow as StockRow
from shared.viewmodels.inventory_viewmodels import WarehouseOption as WarehouseOption
from shared.viewmodels.inventory_viewmodels import (
    stock_delete_confirm as stock_delete_confirm,
)
from shared.viewmodels.inventory_viewmodels import (
    inventory_catalogue as inventory_catalogue,
)
from shared.viewmodels.inventory_viewmodels import stock_detail as stock_detail
from shared.viewmodels.inventory_viewmodels import stock_form as stock_form
from shared.viewmodels.inventory_viewmodels import stock_list as stock_list
from shared.viewmodels.inventory_viewmodels import BusySkuRow as BusySkuRow
from shared.viewmodels.inventory_viewmodels import CsvExport as CsvExport
from shared.viewmodels.inventory_viewmodels import MovedSkuRow as MovedSkuRow
from shared.viewmodels.inventory_viewmodels import RankedStockRow as RankedStockRow
from shared.viewmodels.inventory_viewmodels import StockReportPage as StockReportPage
from shared.viewmodels.inventory_viewmodels import (
    WarehouseStatsRow as WarehouseStatsRow,
)
from shared.viewmodels.inventory_viewmodels import stock_report as stock_report
from shared.viewmodels.inventory_viewmodels import (
    stock_movements_export as stock_movements_export,
)
from shared.viewmodels.inventory_viewmodels import (
    low_stock_alerts as low_stock_alerts,
)
from shared.viewmodels.inventory_viewmodels import (
    movement_book as movement_book,
)
from shared.viewmodels.inventory_viewmodels import warehouse_sheet as warehouse_sheet
