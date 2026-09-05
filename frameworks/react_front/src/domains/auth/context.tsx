/**
 * Who is logged in, for the whole tree.
 *
 * There is exactly ONE copy of that answer in the app and it lives here, because the alternative is
 * every page asking `/api/auth/me` on mount and the topbar disagreeing with the page under it while
 * one of the two is still in flight.
 *
 * `status` is three states and not a boolean with a loading flag beside it. "We have not asked yet"
 * is genuinely different from "we asked and there is nobody", and collapsing them is what makes a
 * guard bounce a logged-in user to the login screen for one frame on every reload.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { AuthContext, type AuthState } from "~/domains/auth/AuthContext";

import { authService, type Credentials, type Registration } from "~/domains/auth/service";
import { isUnauthorized } from "~/core/http/client";
import type { User } from "~/domains/accounts/types";

type AuthStatus = "checking" | "authenticated" | "anonymous";


export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    /**
     * The boot question, asked once. A 401 here is the ANSWER — "nobody is logged in" — and not a
     * failure, so it settles the state instead of surfacing as an error.
     */
    let cancelled = false;
    authService
      .me()
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setStatus("authenticated");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setUser(null);
        setStatus("anonymous");
        if (!isUnauthorized(error)) {
          // The backend is down, or the proxy is not pointing at it. That is worth saying out loud
          // in the console: "you are not logged in" would be a comforting lie about a dead server.
          console.error("Could not reach the API while checking the session.", error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (credentials: Credentials) => {
    const me = await authService.login(credentials);
    setUser(me);
    setStatus("authenticated");
    return me;
  }, []);

  const register = useCallback(async (registration: Registration) => {
    // Registering does NOT sign you in: the three demos send you to the login form afterwards, and
    // this client keeps that behaviour rather than inventing a fourth one.
    return authService.register(registration);
  }, []);

  const logout = useCallback(async () => {
    try {
      await authService.logout();
    } finally {
      // Whatever the server said, this browser is done with that session. Keeping the user on
      // screen because the logout call failed would show a signed-in header over a dead cookie.
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  const value = useMemo<AuthState>(
    () => ({ status, user, login, register, logout }),
    [status, user, login, register, logout],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
