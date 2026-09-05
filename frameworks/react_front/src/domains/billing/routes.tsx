/**
 * The billing routes. THREE and no more: there is no create, update or delete, and that absence is
 * the domain's whole statement — an invoice is raised by an operation and settled by another, never
 * typed into a form. The API offers no such endpoints either.
 */

import { defineDomain } from "~/core/routing/domain";
import { BillingReportPage } from "~/domains/billing/pages/BillingReportPage";
import { InvoiceDetailPage } from "~/domains/billing/pages/InvoiceDetailPage";
import { InvoiceListPage } from "~/domains/billing/pages/InvoiceListPage";

export const billingRoutes = defineDomain("/billing", {
  list: { segment: "", element: <InvoiceListPage />, nav: "Invoices" },
  detail: { segment: ":invoiceId", element: <InvoiceDetailPage /> },
  report: { segment: "report", element: <BillingReportPage />, nav: "Report" },
});
