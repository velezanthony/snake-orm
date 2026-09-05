/**
 * The only domain where two customers want the same unit. Money arrives as a STRING — a `Decimal` on the Python side — and stays one.
 */

export interface Order {
  id: number;
  reference: string;
  state: string;
  total: string;
  customer_id: number;
  warehouse_id: number;
  invoice_id: number | null;
  placed_at: string;
  customer?: string;
  warehouse?: string;
  invoice_amount_cents?: number | null;
}

export interface OrderLine {
  order_id: number;
  sku_id: number;
  quantity: number;
  unit_price: string;
  sku?: string;
}

export interface CustomerOrders {
  id: number;
  username: string;
  order_count: number;
  /** `"None"` when the customer has no orders: a `Decimal | None` serialised with `str()`. */
  ordered_total: string;
}

export interface OrdersPerState {
  state: string;
  orders: number;
  total: string;
}
