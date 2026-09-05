/**
 * Orders: the domain where two customers want the same unit. Everything past `list` is an
 * OPERATION — reserve, settle, attach an invoice, cancel — and each one is a POST that either
 * succeeds or comes back with a `detail` naming what stopped it.
 */

import { exportUrl, query, request, requestList } from "~/core/http/client";
import type { Page } from "~/core/http/shapes";
import type { CustomerOrders, Order, OrderLine, OrdersPerState } from "~/domains/orders/types";

export interface OrderDraft {
  /** UNIQUE, and checked LAST on purpose: another request can turn it taken while a form is open. */
  reference: string;
  customer_id: number;
  warehouse_id: number;
  /** Pairs. The API prices each line off its SKU — the client never sends a price. */
  lines: { sku_id: number; quantity: number }[];
}

export const ordersService = {
  list: () => requestList<Order>("/api/orders"),

  page: (page: number) => request<Page<Order>>(`/api/orders/page${query({ page })}`),

  get: (orderId: number) => request<Order>(`/api/orders/${orderId}`),

  lines: (orderId: number) => requestList<OrderLine>(`/api/orders/${orderId}/lines`),

  report: () => request<{ customers: CustomerOrders[] }>("/api/orders/report"),

  perState: () => requestList<OrdersPerState>("/api/orders/states"),

  customers: () => requestList<CustomerOrders>("/api/orders/customers"),

  ofCustomer: (customerId: number) =>
    requestList<Order>(`/api/orders/customers/${customerId}`),

  create: (draft: OrderDraft) => request<Order>("/api/orders", { method: "POST", body: draft }),

  /** 409 while the order still has lines: the foreign key from them is RESTRICT. */
  remove: (orderId: number) => request<void>(`/api/orders/${orderId}`, { method: "DELETE" }),

  /**
   * States how many units of a SKU the order wants. An UPSERT, and a PUT because of it.
   *
   * The verb IS the operation: setting a quantity is idempotent and survives a retried request,
   * while adding would quietly double what the customer asked for.
   */
  setLine: (orderId: number, body: { sku_id: number; quantity: number }) =>
    request<OrderLine>(`/api/orders/${orderId}/lines`, { method: "PUT", body }),

  /** BOTH halves of the key are required: a line is identified by the pair (order, SKU). */
  removeLine: (orderId: number, skuId: number) =>
    request<{ deleted: boolean }>(`/api/orders/${orderId}/lines/${skuId}`, { method: "DELETE" }),

  /**
   * Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK. All of them or none.
   *
   * A shortage on any line refuses the WHOLE order with a 409: a partial reservation is not a state
   * this domain has, and units held for an order that will never ship are indistinguishable from
   * units held for one that will.
   */
  reserve: (orderId: number) => request<Order>(`/api/orders/${orderId}/reserve`, { method: "POST" }),

  /**
   * Bills a RESERVED order, takes the money and ships it. A declined charge answers 402.
   *
   * The invoice is issued OUTSIDE the savepoint and survives the decline, because a customer who has
   * been sent a bill has been sent a bill; the payment, the shipment and the final state are inside
   * it, because those must not exist if the money did not arrive.
   */
  settle: (orderId: number, body: { subscription_id: number; method?: string }) =>
    request<Order>(`/api/orders/${orderId}/settle`, { method: "POST", body }),

  attachInvoice: (orderId: number, body: { invoice_id: number }) =>
    request<Order>(`/api/orders/${orderId}/invoice`, { method: "POST", body }),

  cancel: (orderId: number) => request<Order>(`/api/orders/${orderId}/cancel`, { method: "POST" }),

  exportUrl: () => exportUrl("/api/orders/export"),
};
