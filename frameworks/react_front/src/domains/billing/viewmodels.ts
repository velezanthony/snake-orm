/**
 * The billing pages as hooks. The mirror of `apps/billing/viewmodels.py`.
 *
 * Everything here counts in whole CENTS, which is the domain's statement and not a formatting
 * preference: an integer is exact, and the division happens once, in `core/lib/money`, on the way to
 * the screen and nowhere else.
 */

import { useResource, type Resource } from "~/core/hooks/useResource";
import type { Page } from "~/core/http/shapes";
import { billingService } from "~/domains/billing/service";
import type { BillingReport, InvoiceRow, Payment } from "~/domains/billing/types";

/** The deepest listing in the demo: THREE to-one hops flattened as LEFT JOINs on one SELECT. */
export function useInvoicePage(page: number): Resource<Page<InvoiceRow>> {
  return useResource(() => billingService.invoicesPage(page), [page]);
}

export interface InvoiceSheet {
  invoice: InvoiceRow;
  payments: Payment[];
}

/**
 * TWO statements, and the second is NOT a join.
 *
 * A to-many in the same SELECT would multiply the invoice row by its payments, so the header would
 * arrive three times for three payments and this page would have to un-multiply it. Asking twice is
 * cheaper than that and honest about the shape.
 */
export function useInvoiceSheet(invoiceId: number): Resource<InvoiceSheet> {
  return useResource(async () => {
    const [invoice, payments] = await Promise.all([
      billingService.invoice(invoiceId),
      billingService.payments(invoiceId),
    ]);
    return { invoice, payments };
  }, [invoiceId]);
}

/** Three statements, and not one of them grows with the number of invoices. */
export function useBillingReport(): Resource<BillingReport> {
  return useResource(() => billingService.report(), []);
}
