/**
 * `href("orders.detail", { orderId: 7 })` — the only way this app writes a URL.
 *
 * React Router ships an `href()` that does exactly this, and it is not usable here: it is available
 * in FRAMEWORK mode only, and this demo is a plain SPA on `createBrowserRouter`. So this is the same
 * idea over the route registry the domains already declare — which is better than the alternative
 * anyway, because the registry is the thing the sidebar and the router are already built from.
 *
 * What it buys, stated plainly: `href("orders.detial", …)` does not compile, `href("orders.detail",
 * { id: 7 })` does not compile, and `href("orders.list", { … })` does not compile either — a route
 * with no params takes no argument. None of those three is catchable in a template literal.
 */

import type { AnyDomain } from "~/core/routing/domain";
import type { HrefArgs } from "~/core/routing/types";

/** Turns a union of object types into their intersection. The standard trick, via contravariance. */
type UnionToIntersection<U> = (U extends unknown ? (value: U) => void : never) extends (
  value: infer I,
) => void
  ? I
  : never;

/** `{ "orders.list": "/orders", "orders.detail": "/orders/:orderId", … }`, as literal types. */
export type FlatRoutes<Domains extends Record<string, AnyDomain>> = UnionToIntersection<
  {
    [Name in keyof Domains & string]: {
      [Route in keyof Domains[Name]["paths"] & string as `${Name}.${Route}`]: Domains[Name]["paths"][Route];
    };
  }[keyof Domains & string]
>;

/**
 * Builds the `href` for a registry of domains.
 *
 * A factory rather than a module-level function because the registry is what gives it its types,
 * and a global would have to import every domain — which is the import cycle a domain-first tree is
 * arranged to avoid.
 */
export function createHref<const Domains extends Record<string, AnyDomain>>(domains: Domains) {
  type Routes = FlatRoutes<Domains>;

  const paths = new Map<string, string>();
  for (const [name, domain] of Object.entries(domains)) {
    for (const [route, path] of Object.entries(domain.paths as Record<string, string>)) {
      paths.set(`${name}.${route}`, path);
    }
  }

  return function href<Name extends keyof Routes & string>(
    name: Name,
    ...args: Routes[Name] extends string ? HrefArgs<Routes[Name]> : never
  ): string {
    const template = paths.get(name);
    // A name the types accept and the map does not hold means the registry and the types disagree,
    // which is a bug in this file rather than in the caller. Loud, and at the first click.
    if (template === undefined) throw new Error(`No route is registered under "${name}".`);

    // Narrowed by hand because `Name` is still generic here: the caller's `HrefArgs`
    // already proved the shape, and inside the body TypeScript cannot re-derive it.
    const params: Record<string, string | number> | undefined = args[0];
    if (params === undefined) return template;

    return template.replace(/:([A-Za-z0-9_]+)/g, (_match, key: string) => {
      const value = params[key];
      if (value === undefined) throw new Error(`The route "${name}" needs a "${key}".`);
      return encodeURIComponent(String(value));
    });
  };
}
