/**
 * The logistics pages as hooks. The mirror of `apps/logistics/viewmodels.py`.
 *
 * Every read here is ONE statement whose cost does not grow with the rows, and saying so is the
 * point of the section: the figures on a depot row are CORRELATED aggregates the engine computes
 * beside the depot they belong to, and walking the relation instead would be the same page at one
 * query per row — an N+1 inside the renderer, where no test counts.
 */

import { useResource, type Resource } from "~/core/hooks/useResource";
import { logisticsService } from "~/domains/logistics/service";
import type { DeliverySheet, Depot, DispatchRow, SlotLoad } from "~/domains/logistics/types";

export function useDepots(): Resource<Depot[]> {
  return useResource(() => logisticsService.depots(), []);
}

/** Backwards scheduling: the deadline is the promise shifted BACKWARD by the lead time. */
export function useDispatchBoard(): Resource<DispatchRow[]> {
  return useResource(() => logisticsService.dispatch(), []);
}

/** A window whose span is a VALUE and not a count of rows, so a tie is not a step. */
export function useSlotLoad(): Resource<SlotLoad[]> {
  return useResource(() => logisticsService.load(), []);
}

/** The ranking is a SQRT over a sum of POWERs the ENGINE computes, so it can be the ORDER BY key. */
export function useDeliverySheet(deliveryId: number): Resource<DeliverySheet> {
  return useResource(() => logisticsService.delivery(deliveryId), [deliveryId]);
}
