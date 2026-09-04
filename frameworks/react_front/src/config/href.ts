/**
 * `href` for this app's registry. One import for every link in the client.
 *
 * IT IS A FUNCTION AND NOT `const href = createHref(DOMAINS)`, and the difference is load-bearing.
 * There is a cycle here and it is inherent rather than accidental: a page wants a typed link, so it
 * imports this; this needs the registry to know the names; the registry holds every domain's routes,
 * and a route holds its page. Pages → href → registry → routes → pages.
 *
 * ES modules survive that as long as the binding is only DEREFERENCED after everything has finished
 * evaluating. Building the table at module scope reads `DOMAINS` during the cycle, and the first
 * module in cycle order gets `undefined` — measured, as a blank page and one line in the console:
 * "Cannot access 'DOMAINS' before initialization". Reading it inside the call defers that to the
 * first click, by which time every module is up.
 *
 * The alternative — splitting each domain's paths away from its elements — would break the cycle
 * structurally and split a route's declaration across two files, which is the drift this whole layer
 * exists to remove. One lazy read is the cheaper price.
 */

import { DOMAINS } from "~/config/routes";
import { createHref, type FlatRoutes } from "~/core/routing/href";
import type { HrefArgs } from "~/core/routing/types";

type Routes = FlatRoutes<typeof DOMAINS>;

let resolve: ((name: string, ...args: unknown[]) => string) | null = null;

export function href<Name extends keyof Routes>(
  name: Name & string,
  ...args: Routes[Name] extends string ? HrefArgs<Routes[Name]> : never
): string {
  resolve ??= createHref(DOMAINS) as unknown as (name: string, ...args: unknown[]) => string;
  return resolve(name, ...args);
}
