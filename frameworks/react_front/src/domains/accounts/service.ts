/** The accounts domain: the roles catalogue and who holds which. */

import { request, requestList } from "~/core/http/client";
import type { Role, UserStats } from "~/domains/accounts/types";

export const accountsService = {
  roles: () => requestList<Role>("/api/accounts/roles"),

  rolesOf: (userId: number) => requestList<Role>(`/api/accounts/users/${userId}/roles`),

  revokeRole: (userId: number, roleId: number) =>
    request<{ revoked: boolean }>(`/api/accounts/users/${userId}/roles/${roleId}`, {
      method: "DELETE",
    }),

  /**
   * The people, from the blog's stats endpoint.
   *
   * The accounts domain has no "every user" route of its own, and inventing a client-side one out
   * of `/api/posts` would mean pulling every post to derive a list of names. `/api/posts/stats`
   * already answers one row per user, computed with a scalar subquery — so the directory reads it,
   * and the extra column it carries is one the page wanted anyway.
   */
  directory: () => request<{ users: UserStats[] }>("/api/posts/stats"),
};
