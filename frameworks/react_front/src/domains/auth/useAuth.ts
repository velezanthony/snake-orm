/**
 * Who is logged in, for whoever asks.
 *
 * Separate from the provider because that file exports a COMPONENT, and a module exporting both a
 * component and a hook breaks Fast Refresh for all of it — every edit to the provider would remount
 * the tree instead of patching it.
 */

import { use } from "react";

import { AuthContext, type AuthState } from "~/domains/auth/AuthContext";

export function useAuth(): AuthState {
  const context = use(AuthContext);
  if (context === null) throw new Error("useAuth must be used inside <AuthProvider>.");
  return context;
}
