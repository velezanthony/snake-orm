/**
 * THE registry: every domain's routes, in the order the sidebar shows them.
 *
 * This is the file `config/urls.py` is on the Python side — the one place that knows which domains
 * exist and where each is mounted — and it is the ONLY thing three separate consumers are built
 * from: the router, the sidebar, and `href`. Before it existed those three each held their own copy
 * of a path, and renaming a route fixed one and broke the other two in silence.
 *
 * The order IS the sidebar's order, which is why it is a declared array and not an object: an object
 * would leave the order to insertion and nobody would know it mattered.
 */

import { accountsRoutes } from "~/domains/accounts/routes";
import { authRoutes } from "~/domains/auth/routes";
import { billingRoutes } from "~/domains/billing/routes";
import { blogRoutes } from "~/domains/blog/routes";
import { contentRoutes } from "~/domains/content/routes";
import { engagementRoutes } from "~/domains/engagement/routes";
import { inventoryRoutes } from "~/domains/inventory/routes";
import { labRoutes } from "~/domains/lab/routes";
import { logisticsRoutes } from "~/domains/logistics/routes";
import { ordersRoutes } from "~/domains/orders/routes";
import { taxonomyRoutes } from "~/domains/taxonomy/routes";

/**
 * Keyed by the name `href` uses — `href("orders.detail")` — and `auth` is deliberately absent from
 * the sidebar rather than from here: it has routes and no section, which the sidebar reads off `nav`.
 */
export const DOMAINS = {
  blog: blogRoutes,
  content: contentRoutes,
  engagement: engagementRoutes,
  inventory: inventoryRoutes,
  orders: ordersRoutes,
  billing: billingRoutes,
  taxonomy: taxonomyRoutes,
  logistics: logisticsRoutes,
  accounts: accountsRoutes,
  lab: labRoutes,
  auth: authRoutes,
} as const;

/** The sidebar's sections, in order. `auth` is not one, which is why the list is explicit. */
export const SIDEBAR = [
  { domain: "blog", label: "Blog" },
  { domain: "content", label: "Content" },
  { domain: "engagement", label: "Engagement" },
  { domain: "inventory", label: "Inventory" },
  { domain: "orders", label: "Orders" },
  { domain: "billing", label: "Billing" },
  { domain: "taxonomy", label: "Tags" },
  { domain: "logistics", label: "Logistics" },
  { domain: "accounts", label: "Accounts" },
  { domain: "lab", label: "Lab" },
] as const satisfies readonly { domain: keyof typeof DOMAINS; label: string }[];
