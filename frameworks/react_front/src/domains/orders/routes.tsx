/**
 * The orders routes. The mirror of `apps/orders/web_urls.py`.
 *
 * `operate` is the one entry beyond `list` and `create` that the sidebar can reach, and the reason
 * is the shape rather than the importance: the bare path is a CHOOSER and the path with an id is the
 * operation, so a link with no key still lands somewhere useful.
 */

import { defineDomain } from "~/core/routing/domain";
import { CustomerSheetPage } from "~/domains/orders/pages/CustomerSheetPage";
import { OrderCreatePage } from "~/domains/orders/pages/OrderCreatePage";
import { OrderDeletePage } from "~/domains/orders/pages/OrderDeletePage";
import { OrderDetailPage } from "~/domains/orders/pages/OrderDetailPage";
import { OrderEditPage } from "~/domains/orders/pages/OrderEditPage";
import { OrderListPage } from "~/domains/orders/pages/OrderListPage";
import { OrderOperateIndexPage } from "~/domains/orders/pages/OrderOperateIndexPage";
import { OrderOperatePage } from "~/domains/orders/pages/OrderOperatePage";
import { OrderReportPage } from "~/domains/orders/pages/OrderReportPage";

export const ordersRoutes = defineDomain("/orders", {
  list: { segment: "", element: <OrderListPage />, nav: "Orders" },
  detail: { segment: ":orderId", element: <OrderDetailPage /> },
  create: { segment: "new", element: <OrderCreatePage />, nav: "New order" },
  update: { segment: ":orderId/edit", element: <OrderEditPage /> },
  delete: { segment: ":orderId/delete", element: <OrderDeletePage /> },
  operate: { segment: "operate", element: <OrderOperateIndexPage />, nav: "Reserve / settle / cancel" },
  customer: { segment: "customer/:customerId", element: <CustomerSheetPage /> },
  report: { segment: "report", element: <OrderReportPage />, nav: "Report" },
  operateOne: { segment: "operate/:orderId", element: <OrderOperatePage /> },
});
