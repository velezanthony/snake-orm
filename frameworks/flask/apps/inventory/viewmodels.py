"""View models of the inventory domain: it re-exports those of `shared.viewmodels` (they live once).

Presentation-ready flat dicts, one function per page of the taxonomy. The views import from HERE and
never from `shared` directly, which is the same rule the selectors and use cases next door follow:
the demo is a wrapper, and a wrapper that reaches around itself stops showing where its own layers
are.

`CsvExport` travels through here too, and it is the one name on the list that is not a page: it is
the SHAPE the export hands the web layer — a filename, a header and a lazy generator of rows. The
view needs the type to write the response, and importing it from `shared` in `urls.py` while every
sibling comes from here is exactly the leak this module exists to close. `MOVEMENT_EXPORT_HEADER`
travels for the same reason one storey up: a test that retyped those nine column names would be a
second spelling of them, which is the drift this whole layer was put in front of.
"""

from shared.viewmodels.inventory_viewmodels import (
    MOVEMENT_EXPORT_HEADER as MOVEMENT_EXPORT_HEADER,
)
from shared.viewmodels.inventory_viewmodels import BusySkuRow as BusySkuRow
from shared.viewmodels.inventory_viewmodels import CsvExport as CsvExport
from shared.viewmodels.inventory_viewmodels import MovedSkuRow as MovedSkuRow
from shared.viewmodels.inventory_viewmodels import MovementRow as MovementRow
from shared.viewmodels.inventory_viewmodels import RankedStockRow as RankedStockRow
from shared.viewmodels.inventory_viewmodels import SkuOption as SkuOption
from shared.viewmodels.inventory_viewmodels import StockDeletePage as StockDeletePage
from shared.viewmodels.inventory_viewmodels import StockDetailPage as StockDetailPage
from shared.viewmodels.inventory_viewmodels import StockFormPage as StockFormPage
from shared.viewmodels.inventory_viewmodels import StockListPage as StockListPage
from shared.viewmodels.inventory_viewmodels import StockReportPage as StockReportPage
from shared.viewmodels.inventory_viewmodels import StockRow as StockRow
from shared.viewmodels.inventory_viewmodels import WarehouseOption as WarehouseOption
from shared.viewmodels.inventory_viewmodels import (
    WarehouseStatsRow as WarehouseStatsRow,
)
from shared.viewmodels.inventory_viewmodels import (
    stock_delete_confirm as stock_delete_confirm,
)
from shared.viewmodels.inventory_viewmodels import (
    inventory_catalogue as inventory_catalogue,
)
from shared.viewmodels.inventory_viewmodels import stock_detail as stock_detail
from shared.viewmodels.inventory_viewmodels import stock_form as stock_form
from shared.viewmodels.inventory_viewmodels import stock_list as stock_list
from shared.viewmodels.inventory_viewmodels import (
    stock_movements_export as stock_movements_export,
)
from shared.viewmodels.inventory_viewmodels import stock_report as stock_report
from shared.viewmodels.inventory_viewmodels import (
    low_stock_alerts as low_stock_alerts,
)
from shared.viewmodels.inventory_viewmodels import (
    movement_book as movement_book,
)
from shared.viewmodels.inventory_viewmodels import warehouse_sheet as warehouse_sheet
