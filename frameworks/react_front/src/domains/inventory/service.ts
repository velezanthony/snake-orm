/**
 * Inventory: the domain with the COMPOSITE key.
 *
 * Stock is identified by the pair (warehouse, sku), so every path that reaches one row carries the
 * key in two halves — which is exactly why this file exists rather than components assembling those
 * URLs by hand. Get one half wrong and you have written to a different row that also exists.
 */

import { exportUrl, query, request, requestList } from "~/core/http/client";
import type { Page } from "~/core/http/shapes";
import type { Sku, StockMovement, StockReport, StockRow, Warehouse, WarehouseStats } from "~/domains/inventory/types";

export const inventoryService = {
  warehouses: () => requestList<Warehouse>("/api/inventory/warehouses"),

  warehouse: (warehouseId: number) => request<Warehouse>(`/api/inventory/warehouses/${warehouseId}`),

  skus: () => requestList<Sku>("/api/inventory/skus"),

  /** The reorder screen: what is running out, across the whole stockroom. */
  lowStock: () => requestList<StockRow>("/api/inventory/low-stock"),

  stats: () => requestList<WarehouseStats>("/api/inventory/stats"),

  stockPage: (page: number) => request<Page<StockRow>>(`/api/inventory/stock/page${query({ page })}`),

  report: () => request<StockReport>("/api/inventory/report"),

  stockOf: (warehouseId: number) =>
    requestList<StockRow>(`/api/inventory/warehouses/${warehouseId}/stock`),

  /**
   * One warehouse's stock WITH the movements of every line, in a single select-in.
   *
   * The hardest relationship in these demos: a stock row is identified by the pair, so every parent
   * binds two placeholders instead of one. Done per line it would be one query per SKU.
   */
  stockWithMovements: (warehouseId: number) =>
    requestList<StockRow & { movements: StockMovement[] }>(
      `/api/inventory/warehouses/${warehouseId}/stock/movements`,
    ),

  /**
   * ONE pair, and FOUR operations told apart by the METHOD rather than by four URLs.
   *
   * `PUT` is a physical count — an upsert, so it says the pair holds this many whether or not the
   * row was already there. `PATCH` corrects the two levels of a row that exists. The verb is the
   * operation, which is also the only way a router that maps a path to one view can offer all four.
   */
  stockPair: (warehouseId: number, skuId: number) =>
    request<StockRow>(`/api/inventory/warehouses/${warehouseId}/stock/${skuId}`),

  countStock: (warehouseId: number, skuId: number, body: { on_hand: number }) =>
    request<StockRow>(`/api/inventory/warehouses/${warehouseId}/stock/${skuId}`, {
      method: "PUT",
      body,
    }),

  correctStock: (warehouseId: number, skuId: number, body: { on_hand: number; reserved: number }) =>
    request<StockRow>(`/api/inventory/warehouses/${warehouseId}/stock/${skuId}`, {
      method: "PATCH",
      body,
    }),

  removeStock: (warehouseId: number, skuId: number) =>
    request<void>(`/api/inventory/warehouses/${warehouseId}/stock/${skuId}`, { method: "DELETE" }),

  movementsOf: (warehouseId: number, skuId: number) =>
    requestList<StockMovement>(`/api/inventory/warehouses/${warehouseId}/stock/${skuId}/movements`),

  receive: (warehouseId: number, skuId: number, body: { units: number }) =>
    request<StockRow>(`/api/inventory/warehouses/${warehouseId}/stock/${skuId}/receive`, {
      method: "POST",
      body,
    }),

  /** 409 if there are not that many: the rule refuses BEFORE writing. */
  ship: (warehouseId: number, skuId: number, body: { units: number }) =>
    request<StockRow>(`/api/inventory/warehouses/${warehouseId}/stock/${skuId}/ship`, {
      method: "POST",
      body,
    }),

  /** Reserves units across the WAREHOUSE's whole stock in one statement. */
  reserve: (warehouseId: number, body: { units: number }) =>
    request<{ rows: number }>(`/api/inventory/warehouses/${warehouseId}/reserve`, {
      method: "POST",
      body,
    }),

  /** A link, not a fetch: the CSV is STREAMED, and the browser receives a stream better than we do. */
  exportUrl: () => exportUrl("/api/inventory/export"),
};
