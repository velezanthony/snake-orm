/** Logistics: depots, the delivery sheet, the dispatch board and the load per slot. */

import { request, requestList } from "~/core/http/client";
import type { DeliverySheet, Depot, DispatchRow, SlotLoad } from "~/domains/logistics/types";

export const logisticsService = {
  depots: () => requestList<Depot>("/api/logistics/depots"),

  delivery: (deliveryId: number) => request<DeliverySheet>(`/api/logistics/deliveries/${deliveryId}`),

  /** What has to leave, and by when: a date computed in SQL, not in the page. */
  dispatch: () => requestList<DispatchRow>("/api/logistics/dispatch"),

  /** Units per hour band, with the window function's total riding alongside each row. */
  load: () => requestList<SlotLoad>("/api/logistics/load"),
};
