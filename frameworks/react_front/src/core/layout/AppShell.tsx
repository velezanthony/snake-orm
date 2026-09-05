/**
 * The shell every page sits in, and the same one `templates/layout/base.html` paints.
 *
 * It is a LAYOUT ROUTE and not a component each page imports, which is the difference between a
 * shell that cannot be forgotten and one that can — the reason Django wires its sidebar into the
 * template engine's context processors instead of leaving it to each view.
 *
 * The auth provider lives here because the topbar and the guards both call `useAuth`, and both are
 * inside the router's element tree.
 */

import { Outlet, ScrollRestoration } from "react-router";

import { currentBackend } from "~/config/backends";
import { DebugDock } from "~/core/debug/DebugDock";
import { Sidebar } from "~/core/layout/Sidebar";
import { Topbar } from "~/core/layout/Topbar";
import { AuthProvider } from "~/domains/auth/context";

export function AppShell() {
  const backend = currentBackend();

  return (
    <AuthProvider>
      <a className="skip" href="#main">
        Skip to content
      </a>

      <Topbar />

      <div className="layout">
        <Sidebar />

        <main className="page" id="main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>

      <footer className="footer">
        <div className="footer-inner">
          <p>
            SnakeORM · the React demo. The same domain, served by three frameworks and rendered by a
            fourth client — right now, {backend.label}.
          </p>
        </div>
      </footer>

      {/* Outside `<main>` and outside the page: the debug tape belongs to the SESSION, not to a route. */}
      <DebugDock />

      {/* Without this, going back to a list drops you at the top of it instead of where you were. */}
      <ScrollRestoration />
    </AuthProvider>
  );
}
