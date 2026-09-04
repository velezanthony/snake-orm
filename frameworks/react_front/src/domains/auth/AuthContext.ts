/**
 * The context itself, and the shape it carries. Nothing else.
 *
 * Its own file because a module that exports a component AND a context breaks Fast Refresh for the
 * whole module: every edit to the provider would remount the tree instead of patching it. The
 * provider is in `context.tsx`, the hook that reads it in `useAuth.ts`.
 */

import { createContext } from "react";

import type { Credentials, Registration } from "~/domains/auth/service";
import type { User } from "~/domains/accounts/types";

/**
 * THREE states and not a boolean with a loading flag beside it.
 *
 * "We have not asked yet" is genuinely different from "we asked and there is nobody", and collapsing
 * them is what makes a guard bounce a logged-in reader to the login screen for one frame on every
 * reload.
 */
export type AuthStatus = "checking" | "authenticated" | "anonymous";

export interface AuthState {
  status: AuthStatus;
  user: User | null;
  login: (credentials: Credentials) => Promise<User>;
  register: (registration: Registration) => Promise<User>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);
