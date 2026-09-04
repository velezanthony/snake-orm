/**
 * The route gate, and the SAME rule Django's `login_required` applies: no session, go to the login.
 *
 * `state={{ from }}` is what makes the bounce forgivable. Sending somebody to the login is fine;
 * sending them to the home page afterwards, having forgotten what they were trying to open, is the
 * part people hate.
 */

import { Navigate, Outlet, useLocation } from "react-router";

import { useAuth } from "~/domains/auth/useAuth";
import { PageSpinner } from "@atoms/Spinner";

export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  // Not "no user yet, so bounce": we have not ASKED yet. Redirecting here would throw every
  // logged-in reader out of the page they reloaded on.
  if (status === "checking") return <PageSpinner label="Checking your session…" />;

  if (status === "anonymous") {
    return <Navigate to="/auth/login" replace state={{ from: location.pathname + location.search }} />;
  }

  return <Outlet />;
}
