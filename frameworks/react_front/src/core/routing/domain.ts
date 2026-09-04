/**
 * A domain declares its routes ONCE, and everything else is derived from that declaration.
 *
 * `defineDomain("/orders", { … })` mirrors what `config/urls.py` does when it mounts
 * `apps.orders.urls` under `orders/`: the prefix is written in one place and the entries underneath
 * are relative to it. The difference is that here the composition happens in the TYPE as well as at
 * runtime, so `paths` carries the finished literal — `"/orders/:orderId"` — and not just `string`.
 *
 * That literal is the whole point. It is what lets `href` know which params a route takes, and it is
 * what turns a renamed route into a compile error at every call site instead of a 404 somebody finds
 * by clicking.
 */

import type { Join, RouteTable } from "~/core/routing/types";

export interface Domain<Prefix extends string, Table extends RouteTable> {
  readonly prefix: Prefix;
  readonly routes: Table;
  /** Each entry's FULL path, composed from the prefix, as a literal type. */
  readonly paths: { readonly [K in keyof Table]: Join<Prefix, Table[K]["segment"]> };
}

/** Joins a prefix and a segment at runtime, the same way `Join` does in the type. */
function join(prefix: string, segment: string): string {
  if (segment === "") return prefix;
  return prefix === "/" ? `/${segment}` : `${prefix}/${segment}`;
}

export function defineDomain<const Prefix extends string, const Table extends RouteTable>(
  prefix: Prefix,
  routes: Table,
): Domain<Prefix, Table> {
  const paths = Object.fromEntries(
    Object.entries(routes).map(([name, route]) => [name, join(prefix, route.segment)]),
  ) as Domain<Prefix, Table>["paths"];
  return { prefix, routes, paths };
}

/**
 * Any domain, for the places that hold a collection of them without caring which.
 *
 * `Domain<string, RouteTable>` and NOT `Domain<any, any>`: the widened form is assignable from every
 * concrete one — a `"/orders"` is a `string` and a declared table is a `RouteTable` — so it does the
 * same job as the constraint without an `any` in a codebase whose whole argument is that the types
 * catch things. An `any` here would have been one imported into every consumer of the registry.
 */
export type AnyDomain = Domain<string, RouteTable>;
