/**
 * The only domain that measures anything: a distance the engine computes, and a window whose span is a value.
 */

export interface Depot {
  code: string;
  name: string;
  deliveries: number;
  units: number;
}

export interface DispatchRow {
  delivery_id: number;
  reference: string;
  promised_on: string;
  leave_by: string;
}

export interface SlotLoad {
  depot: string;
  slot_hour: number;
  units: number;
  band_units: number;
  is_peak: boolean;
}

export interface DepotDistance {
  depot_id: number;
  code: string;
  name: string;
  distance: number;
  assigned: boolean;
  nearest: boolean;
}

export interface PackingSlip {
  units: number;
  per_box: number;
  boxes: number;
  full_boxes: number;
  loose_units: number;
}

export interface DeliverySheet {
  delivery_id: number;
  reference: string;
  depot: string;
  packaging: string;
  slot_hour: number;
  promised_on: string;
  nearest: DepotDistance[];
  packing: PackingSlip;
  is_routed_to_the_nearest: boolean;
}
