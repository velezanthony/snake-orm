/**
 * The auth PAGES. The mirror of `apps/auth/web_urls.py`.
 *
 * None of them is in the sidebar, and that is the SSR demo's decision rather than an oversight: a
 * sidebar of DOMAINS is a table of contents for the demo's data, and the login, the sign-up and
 * somebody's access ledger are reached from the topbar and from that person's row in `accounts`.
 */

import { defineDomain } from "~/core/routing/domain";
import { AccessPage } from "~/domains/auth/pages/AccessPage";
import { LoginPage } from "~/domains/auth/pages/LoginPage";
import { RegisterPage } from "~/domains/auth/pages/RegisterPage";

export const authRoutes = defineDomain("/auth", {
  login: { segment: "login", element: <LoginPage /> },
  register: { segment: "register", element: <RegisterPage /> },
  access: { segment: "access/:userId", element: <AccessPage />, gated: true },
});
