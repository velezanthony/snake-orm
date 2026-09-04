/**
 * The router, BUILT from the registry rather than written beside it.
 *
 * `config/urls.py` is what this mirrors: it names the domains and mounts each one, and the routes
 * themselves live in the domain that owns them. Nothing here lists a path.
 *
 * No `lazy`, and that is a decision: route-level splitting buys a smaller first download and pays
 * with a spinner on the first visit to each section, and this demo is read end to end on localhost
 * where the download is free and the spinner is the only thing anyone would notice.
 */

import { createBrowserRouter, type RouteObject } from "react-router";

import { DOMAINS } from "~/config/routes";
import { RequireAuth } from "~/core/routing/RequireAuth";
import { AppShell } from "~/core/layout/AppShell";
import { ErrorPage, NotFoundPage } from "~/core/layout/ErrorPage";
import type { RouteDefinition } from "~/core/routing/types";

/** Every declared route, flattened, with the gated ones held back for the guard to wrap. */
function collect(): { open: RouteObject[]; gated: RouteObject[] } {
  const open: RouteObject[] = [];
  const gated: RouteObject[] = [];
  for (const domain of Object.values(DOMAINS)) {
    for (const [name, route] of Object.entries(domain.routes as Record<string, RouteDefinition>)) {
      const path = (domain.paths as Record<string, string>)[name];
      // The blog's index is mounted at `/`, and React Router wants that one as `index` rather than
      // as a path — the only entry in the registry that needs saying twice.
      const object: RouteObject = path === "/" ? { index: true, element: route.element } : { path, element: route.element };
      (route.gated ? gated : open).push(object);
    }
  }
  return { open, gated };
}

const { open, gated } = collect();

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    errorElement: <ErrorPage />,
    children: [
      ...open,
      // The session gate, drawn ONCE, which is the same line Django draws with `@login_required`.
      { element: <RequireAuth />, children: gated },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
