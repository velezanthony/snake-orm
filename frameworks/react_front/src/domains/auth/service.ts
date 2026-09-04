/**
 * The auth surface: the three POSTs the demos have always had, plus the GET this client needed.
 *
 * Nothing here touches a token or a header. The session is a cookie the browser holds and the
 * script cannot read, so "am I logged in?" is a REQUEST — `me()` — and never a variable.
 */

import { request, requestList } from "~/core/http/client";
import type { Role, User } from "~/domains/accounts/types";
import type { ApiToken, LoginSession } from "~/domains/auth/types";

export interface Credentials {
  username: string;
  password: string;
}

export interface Registration extends Credentials {
  email: string;
}

export const authService = {
  /** 401 when there is no session. That status is the answer, not an error to hide. */
  me: () => request<User>("/api/auth/me"),

  login: (credentials: Credentials) =>
    request<User>("/api/auth/login", { method: "POST", body: credentials }),

  register: (registration: Registration) =>
    request<User>("/api/auth/register", { method: "POST", body: registration }),

  logout: () => request<{ logged_out: boolean }>("/api/auth/logout", { method: "POST" }),

  /** One person's API tokens: the ledger `/auth/access/<id>/` reads. */
  tokensOf: (userId: number) => requestList<ApiToken>(`/api/auth/users/${userId}/tokens`),

  activeTokensOf: (userId: number) =>
    requestList<ApiToken>(`/api/auth/users/${userId}/tokens/active`),

  /** One person's open login sessions. */
  sessionsOf: (userId: number) =>
    requestList<LoginSession>(`/api/auth/users/${userId}/sessions`),

  rolesOf: (userId: number) => requestList<Role>(`/api/accounts/users/${userId}/roles`),
};
