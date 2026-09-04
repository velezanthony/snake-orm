/**
 * The inventory routes. The mirror of `apps/inventory/web_urls.py`.
 *
 * The literal segments are declared BEFORE `:warehouseId/:skuId`, and the order is load-bearing in
 * the reading even though the router ranks by specificity: `new` is not a warehouse id.
 */

import { defineDomain } from "~/core/routing/domain";
import { CataloguePage } from "~/domains/inventory/pages/CataloguePage";
import { StockAlertsPage } from "~/domains/inventory/pages/StockAlertsPage";
import { StockCreatePage } from "~/domains/inventory/pages/StockCreatePage";
import { StockDeletePage } from "~/domains/inventory/pages/StockDeletePage";
import { StockDetailPage } from "~/domains/inventory/pages/StockDetailPage";
import { StockEditPage } from "~/domains/inventory/pages/StockEditPage";
import { StockListPage } from "~/domains/inventory/pages/StockListPage";
import { StockReportPage } from "~/domains/inventory/pages/StockReportPage";
import { WarehouseSheetPage } from "~/domains/inventory/pages/WarehouseSheetPage";

export const inventoryRoutes = defineDomain("/inventory", {
  list: { segment: "", element: <StockListPage />, nav: "Stock" },
  detail: { segment: ":warehouseId/:skuId", element: <StockDetailPage /> },
  create: { segment: "new", element: <StockCreatePage />, nav: "New stock row" },
  update: { segment: ":warehouseId/:skuId/edit", element: <StockEditPage /> },
  delete: { segment: ":warehouseId/:skuId/delete", element: <StockDeletePage /> },
  catalogue: { segment: "catalogue", element: <CataloguePage />, nav: "Warehouses & SKUs" },
  alerts: { segment: "alerts", element: <StockAlertsPage />, nav: "Running out" },
  warehouse: { segment: "warehouse/:warehouseId", element: <WarehouseSheetPage /> },
  report: { segment: "report", element: <StockReportPage />, nav: "Report" },
});
