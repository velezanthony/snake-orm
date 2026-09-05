/**
 * Billing: the domain that counts in whole CENTS.
 *
 * Every amount here is an integer, and it stays one all the way to the formatter. This is the one
 * domain where a float would be a bug rather than a rounding preference.
 */

import { query, request, requestList } from "~/core/http/client";
import type { Page } from "~/core/http/shapes";
import type { BillingReport, Invoice, InvoiceRow, Payment, Plan } from "~/domains/billing/types";

export const billingService = {
  plans: () => requestList<Plan>("/api/billing/plans"),

  report: () => request<BillingReport>("/api/billing/report"),

  unpaid: () => requestList<Invoice>("/api/billing/invoices/unpaid"),

  invoicesPage: (page: number) =>
    request<Page<InvoiceRow>>(`/api/billing/invoices/page${query({ page })}`),

  invoice: (invoiceId: number) => request<InvoiceRow>(`/api/billing/invoices/${invoiceId}`),

  payments: (invoiceId: number) =>
    requestList<Payment>(`/api/billing/invoices/${invoiceId}/payments`),

  pay: (invoiceId: number, body: { amount_cents: number }) =>
    request<Invoice>(`/api/billing/invoices/${invoiceId}/pay`, { method: "POST", body }),

  subscriptionsOf: (userId: number) =>
    requestList<Record<string, unknown>>(`/api/billing/users/${userId}/subscriptions`),

  invoicesOf: (userId: number) =>
    requestList<Invoice>(`/api/billing/users/${userId}/invoices`),

  subscribe: (body: { user_id: number; plan_id: number }) =>
    request<Record<string, unknown>>("/api/billing/subscriptions", { method: "POST", body }),

  cancelSubscription: (subscriptionId: number) =>
    request<{ cancelled: boolean }>(`/api/billing/subscriptions/${subscriptionId}`, {
      method: "DELETE",
    }),
};
