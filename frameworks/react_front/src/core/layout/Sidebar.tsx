/**
 * The sidebar, WALKED from the route registry instead of from a list of its own.
 *
 * A page appears here when its route declares a `nav`, and it is absent otherwise — which is the
 * catalogue's rule stated in the one place that can enforce it: `detail`, `update` and `delete` all
 * need a key, and a sidebar link has nowhere to get one. Before this, a second file repeated every
 * path and its label, and the two could disagree without anything noticing.
 *
 * The `export` entries are the one shape that is NOT a route. What they reach is a streamed CSV, so
 * they are declared here as links at the API — the same entry Django's `_URL_NAMES` gives them, for
 * the reason it gives: the sidebar's job is to reach the route, and what the route hands back is the
 * route's business.
 */

import { NavLink } from "react-router";

import { apiUrl } from "~/config/backends";
import { DOMAINS, SIDEBAR } from "~/config/routes";
import type { RouteDefinition } from "~/core/routing/types";

/** The blurb under each section: what the domain is FOR, in one line. Mirrors `shared/web/nav.py`. */
const BLURBS: Record<string, string> = {
  blog: "The everyday shape: to-one and to-many relations loaded without N+1, and the N-N of tags resolved with a subquery over the bridge table.",
  content:
    "The only section that asks for the same table twice on purpose: the timeline of a post DEFERS the body — every column except the one that is the size of an article — and the panel under it brings the bodies. Two questions, and the difference between them is a page rather than a paragraph.",
  engagement:
    "Where a TRIGGER becomes visible: the visit counter on a post is moved by the engine, underneath the object the handler is holding, so recording a visit answers with a row REFRESHED from the database rather than with a number Python added up. It is the one figure on the demo no page could work out for itself.",
  inventory:
    "The hard shape: stock is identified by the PAIR (warehouse, sku), so the key travels in the URL in two halves and the movements hang off a foreign key two columns wide.",
  orders:
    "The only section where two customers want the same unit: a transaction that declares its isolation level before it reads, holds the stock under a row lock while it decides, and rewinds a declined payment to a savepoint without losing the invoice it had already issued.",
  billing:
    "The money, read-only on purpose: an invoice is raised by an operation and settled by another, never typed into a form. Three pages instead of five, and the one listing in the demos that flattens THREE to-one hops per row without paying a query for any of them.",
  taxonomy:
    "The only N—N in the catalogue with an explicit bridge, and the section where a set operation earns its place: requiring two tags is a condition on two DIFFERENT bridge rows, so no WHERE expresses it and the engine is asked to INTERSECT. Ticking a box twice is also why tagging had to become idempotent.",
  logistics:
    "The only section that measures anything: the depot a delivery should leave from is a distance — a square root over a sum of squares the engine computes so that only the three nearest travel — and the load of an hour is a window whose span is a VALUE rather than a count of rows, so two vans booked at nine read one figure instead of three.",
  accounts:
    "The administrative N—N: roles and who holds them, over a bridge table with no payload at all. The grants screen is the tag screen with different nouns, which is the point of having a page taxonomy — the same operation looks the same wherever a reader meets it.",
  lab: "The ORM with the lid off: aggregates, subqueries, joins and pagination, plus a page that provokes an N+1 on purpose so the debug panel flags it.",
};

/** The CSV a domain offers, if it offers one. A path at the API, never a route of this client. */
const EXPORTS: Record<string, string> = {
  inventory: "/api/inventory/export",
  orders: "/api/orders/export",
  engagement: "/api/engagement/visits/export",
};

export function Sidebar() {
  return (
    <nav className="sidebar" aria-label="Domains">
      {SIDEBAR.map(({ domain, label }) => {
        const routes = DOMAINS[domain].routes as Record<string, RouteDefinition>;
        const paths = DOMAINS[domain].paths as Record<string, string>;
        const csv = EXPORTS[domain];

        return (
          <div className="sidebar-group" key={domain}>
            <p className="sidebar-title">{label}</p>

            {Object.entries(routes)
              .filter(([, route]) => route.nav !== undefined)
              .map(([name, route]) => (
                <NavLink
                  key={name}
                  className="sidebar-link"
                  to={paths[name] ?? "/"}
                  // `end` everywhere: without it `/inventory` lights up while you are reading
                  // `/inventory/report`, and the sidebar claims you are on two pages at once.
                  end
                >
                  {route.nav}
                </NavLink>
              ))}

            {csv ? (
              <a className="sidebar-link" href={apiUrl(csv)}>
                Export CSV
              </a>
            ) : null}

            <p className="sidebar-blurb">{BLURBS[domain]}</p>
          </div>
        );
      })}
    </nav>
  );
}
