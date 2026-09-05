/**
 * The orders pages as hooks. The mirror of `apps/orders/viewmodels.py`, which is 1.153 lines of it.
 *
 * This is the domain where the composition matters most, and the Python layer says why: the
 * operation page runs SEVEN statements and none of them grows with the number of lines, because the
 * stock is read for the WAREHOUSE and matched to the lines here rather than looked up per line. A
 * lookup per line would be correct, invisible on a two-line order, and an N+1 on the page whose
 * entire subject is what happens under load.
 *
 * AND A READ IS NOT AN OPERATION. `useOrderOperation` fetches and does nothing else: each of the
 * three operations opens by DECLARING its isolation level, which the engine only accepts before a
 * transaction has read anything, so a page that had already read would poison the one it leads to.
 */

import { useResource, type Resource } from "~/core/hooks/useResource";
import type { Page } from "~/core/http/shapes";
import { inventoryService } from "~/domains/inventory/service";
import type { Sku, Warehouse } from "~/domains/inventory/types";
import { ordersService, type OrderDraft } from "~/domains/orders/service";
import type { CustomerOrders, Order, OrderLine, OrdersPerState } from "~/domains/orders/types";

/** The rows and one COUNT for the pager, whatever the size of the page. */
export function useOrderPage(page: number): Resource<Page<Order>> {
  return useResource(() => ordersService.page(page), [page]);
}

export interface OrderSheet {
  order: Order;
  lines: OrderLine[];
}

/** The order and the to-many over the demo's SECOND composite key: order and SKU together. */
export function useOrderSheet(orderId: number): Resource<OrderSheet> {
  return useResource(async () => {
    const [order, lines] = await Promise.all([
      ordersService.get(orderId),
      ordersService.lines(orderId),
    ]);
    return { order, lines };
  }, [orderId]);
}

/** The open orders: the states an operation is still reachable from. */
export function useOpenOrders(): Resource<Order[]> {
  const OPEN = new Set(["draft", "reserved", "invoiced"]);
  return useResource(async () => (await ordersService.list()).filter((o) => OPEN.has(o.state)), []);
}

/**
 * The operation page, and the RE-READ after each one.
 *
 * `reserve` and `cancel` move the order AND the stock, so anything the component was holding is a
 * screenshot of a state that no longer exists — which is the argument `_operate_page` makes in the
 * Django view, in those words.
 */
export function useOrderOperation(orderId: number) {
  const sheet = useOrderSheet(orderId);
  return {
    sheet,
    operate: async (run: () => Promise<unknown>) => {
      await run();
      sheet.reload();
    },
  };
}

export interface OrderReport {
  customers: CustomerOrders[];
  states: OrdersPerState[];
}

/** Two aggregates the ENGINE computes; neither grows with the number of orders. */
export function useOrderReport(): Resource<OrderReport> {
  return useResource(async () => {
    const [report, states] = await Promise.all([ordersService.report(), ordersService.perState()]);
    return { customers: report.customers, states };
  }, []);
}

export function useCustomerOrders(customerId: number): Resource<Order[]> {
  return useResource(() => ordersService.ofCustomer(customerId), [customerId]);
}

export interface OrderCatalogue {
  warehouses: Warehouse[];
  skus: Sku[];
}

/**
 * What an order can be placed AGAINST. It reaches into inventory, and that is the domain's shape
 * rather than a leak: an order line points at a SKU, and a customer picking one needs to see them.
 */
export function useOrderCatalogue(): Resource<OrderCatalogue> {
  return useResource(async () => {
    const [warehouses, skus] = await Promise.all([
      inventoryService.warehouses(),
      inventoryService.skus(),
    ]);
    return { warehouses, skus };
  }, []);
}

/** The writes. Each one commits on its own — never a single button covering several. */
export const orderWrites = {
  place: (draft: OrderDraft) => ordersService.create(draft),
  setLine: (orderId: number, body: { sku_id: number; quantity: number }) =>
    ordersService.setLine(orderId, body),
  removeLine: (orderId: number, skuId: number) => ordersService.removeLine(orderId, skuId),
  remove: (orderId: number) => ordersService.remove(orderId),
};
