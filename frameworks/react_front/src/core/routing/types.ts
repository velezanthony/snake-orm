/**
 * The route table's TYPES: what a domain declares, and what `href` can be asked for.
 *
 * The whole point of this file is that a path is written ONCE, in the domain that owns it, and
 * everything else — the router, the sidebar, every link — is derived from it. Before it existed,
 * three separate things knew a path: the router, the sidebar catalogue and thirty template literals
 * spelling `/orders/${order.id}` by hand. Renaming a route fixed one of the three and broke the
 * other two in silence, because a template literal cannot be wrong at compile time.
 *
 * The prefix composition mirrors Django: `config/urls.py` mounts `apps.orders.urls` under
 * `orders/`, and the routes inside are written relative to it. Here a domain declares its prefix
 * once and its entries carry the segment underneath.
 */

import type { ReactElement } from "react";

/** The `:param` names inside a path, as a union of literals. `never` when the path takes none. */
export type PathParams<Path extends string> = Path extends `${string}:${infer Tail}`
  ? Tail extends `${infer Name}/${infer Rest}`
    ? Name | PathParams<`/${Rest}`>
    : Tail
  : never;

/**
 * The arguments `href` demands for a path: an object with exactly its params, or nothing at all.
 *
 * A tuple rather than a plain parameter so a path with no params takes NO second argument — passing
 * one is then a compile error rather than a value silently ignored.
 */
export type HrefArgs<Path extends string> = [PathParams<Path>] extends [never]
  ? []
  : [params: Record<PathParams<Path>, string | number>];

/** One route of a domain. `segment` is relative to the domain's prefix, never the whole path. */
export interface RouteDefinition {
  /** Relative to the domain prefix. `""` is the domain's own index. */
  readonly segment: string;
  readonly element: ReactElement;
  /** Behind the session gate, the same line Django draws with `@login_required`. */
  readonly gated?: boolean;
  /**
   * What the sidebar calls it. ABSENT means "not in the sidebar", which is the catalogue's rule
   * rather than an omission: `detail`, `update` and `delete` all need a key, and a sidebar link has
   * nowhere to get one.
   */
  readonly nav?: string;
}

export type RouteTable = Readonly<Record<string, RouteDefinition>>;

/** Joins a prefix and a segment the way a router does, without doubling or dropping the slash. */
export type Join<Prefix extends string, Segment extends string> = Segment extends ""
  ? Prefix
  : Prefix extends "/"
    ? `/${Segment}`
    : `${Prefix}/${Segment}`;
