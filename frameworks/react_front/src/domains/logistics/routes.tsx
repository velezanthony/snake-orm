/**
 * The logistics routes. No create, update or delete: a delivery is booked by whatever system takes
 * the customer's order and a depot is a building somebody surveyed. Neither is a form.
 */

import { defineDomain } from "~/core/routing/domain";
import { DeliverySheetPage } from "~/domains/logistics/pages/DeliverySheetPage";
import { DepotListPage } from "~/domains/logistics/pages/DepotListPage";
import { DispatchBoardPage } from "~/domains/logistics/pages/DispatchBoardPage";
import { SlotLoadPage } from "~/domains/logistics/pages/SlotLoadPage";

export const logisticsRoutes = defineDomain("/logistics", {
  list: { segment: "", element: <DepotListPage />, nav: "Depots" },
  detail: { segment: "deliveries/:deliveryId", element: <DeliverySheetPage /> },
  dispatch: { segment: "dispatch", element: <DispatchBoardPage />, nav: "Dispatch board" },
  load: { segment: "load", element: <SlotLoadPage />, nav: "Slot load" },
});
