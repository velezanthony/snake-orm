/**
 * The domain with the COMPOSITE key: stock is identified by the PAIR (warehouse, sku), and every shape here carries both halves.
 */

export interface Warehouse {
  id: number;
  code: string;
  name: string;
  active: boolean;
  opened_on: string;
  shift_start: string;
  cutoff: string;
}

export interface Sku {
  id: number;
  public_id: string;
  name: string;
  kind: string;
  price: string;
  weight_kg: number;
  lead_time_seconds: number;
  thumbnail_bytes: number;
  attrs: Record<string, unknown>;
  related_ids: number[];
}

export interface StockRow {
  warehouse_id: number;
  sku_id: number;
  on_hand: number;
  reserved: number;
  /** Computed by the engine — `on_hand - reserved` — and not by this client. */
  available?: number;
  counted_at?: string | null;
  counted_local?: string | null;
  warehouse?: string;
  sku?: string;
}

export interface WarehouseStats {
  warehouse: Warehouse;
  sku_count: number;
  total_units: number;
}

export interface StockMovement {
  id: number;
  warehouse_id: number;
  sku_id: number;
  quantity: number;
  reason: string;
  happened_at: string;
}

export interface BusySku {
  sku_name: string;
  moves: number;
  net_delta: number;
}

export interface StockRanking {
  warehouse_code: string;
  sku_name: string;
  on_hand: number;
  position: number;
}

export interface MovementTrail {
  sku_name: string;
  delta: number;
  running: number;
  moving: number;
}

export interface StockReport {
  warehouses: WarehouseStats[];
  busy_skus: BusySku[];
  ranking: StockRanking[];
  moved_skus: { sku_id: number; sku_name: string }[];
  total_skus: number;
  trail: MovementTrail[];
}
