/**
 * The route types keep their promise, asserted by the COMPILER rather than at runtime.
 *
 * `tsc` is the runner here: every `@ts-expect-error` below fails the build if the line it guards
 * ever starts compiling. That is the only way to test a guarantee that exists only at compile time —
 * a runtime test cannot observe a call that was supposed to be impossible to write.
 *
 * It matters because the guarantee is the entire reason this layer exists. `href` replaced thirty
 * hand-written template literals like `/orders/${order.id}`, and a template literal cannot be wrong
 * at compile time: rename the route and every one of them keeps compiling and starts 404ing. If
 * `href` ever degrades to accepting `string`, it becomes those thirty literals with extra steps, and
 * nothing else in the suite would notice.
 *
 * This file is never imported. `tsconfig.json` includes it, which is all it needs to be checked.
 */

import { defineDomain } from "~/core/routing/domain";
import { createHref } from "~/core/routing/href";

const orders = defineDomain("/orders", {
  list: { segment: "", element: <div />, nav: "Orders" },
  detail: { segment: ":orderId", element: <div /> },
});

const inventory = defineDomain("/inventory", {
  // The composite key, which is the shape worth pinning: two params in one path, and the demo's
  // hardest relationship. Half a key is the mistake this catches.
  pair: { segment: ":warehouseId/:skuId", element: <div /> },
});

const href = createHref({ orders, inventory });

// --- what must compile ---------------------------------------------------------------------------

const _index: string = href("orders.list");
const _one: string = href("orders.detail", { orderId: 7 });
const _pair: string = href("inventory.pair", { warehouseId: 1, skuId: 2 });

// The paths compose from the prefix, and they do it in the TYPE and not only at runtime.
const _composed: "/orders/:orderId" = orders.paths.detail;
const _bare: "/orders" = orders.paths.list;

// --- what must NOT compile -----------------------------------------------------------------------

// @ts-expect-error a route name that does not exist
href("orders.detial", { orderId: 7 });

// @ts-expect-error the param is called `orderId`, not `id`
href("orders.detail", { id: 7 });

// @ts-expect-error `orders.list` takes no params, so it takes no second argument
href("orders.list", { orderId: 7 });

// @ts-expect-error half of a composite key is not a key
href("inventory.pair", { warehouseId: 1 });

// @ts-expect-error a route WITH params cannot be called without them
href("orders.detail");

export const _checked = [_index, _one, _pair, _composed, _bare];
