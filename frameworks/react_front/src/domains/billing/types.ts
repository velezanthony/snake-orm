/**
 * The domain that counts in whole CENTS. An integer there is exact, and the formatting is the view's problem.
 */

export interface Plan {
  id: number;
  name: string;
  price_cents: number;
}

export interface Invoice {
  id: number;
  amount_cents: number;
  paid: boolean;
  subscription_id: number;
  issued_at: string;
}

export interface PlanWithCount extends Plan {
  subscription_count: number;
}

export interface PlanRevenue {
  plan: string;
  invoice_count: number;
  revenue_cents: number;
}

export interface OverdueInvoice {
  invoice_id: number;
  amount_cents: number;
  due: string;
  collected: number;
}

export interface BillingReport {
  plans: PlanWithCount[];
  revenue: PlanRevenue[];
  unpaid_count: number;
  unpaid_cents: number;
  overdue: OverdueInvoice[];
}

/** An invoice row with its three to-one hops already flattened: subscription → plan, and → user. */
export interface InvoiceRow extends Invoice {
  customer_id: number;
  customer: string;
  plan_id: number;
  plan: string;
  plan_price_cents: number;
}

export interface Payment {
  id: number;
  invoice_id: number;
  amount_cents: number;
  method: string;
  paid_at: string;
}
