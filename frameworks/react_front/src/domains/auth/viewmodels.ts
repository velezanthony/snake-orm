/**
 * The auth pages as hooks. The mirror of `apps/auth/viewmodels.py`.
 *
 * The ledger READS and does not mint, which is the line `apps/auth/views.access` draws: issuing a
 * token and revoking one stay on the JSON surface, because a token is for a client with no cookie
 * jar and a browser gets a signed session. A ledger you can read is not a mint.
 */

import { useResource, type Resource } from "~/core/hooks/useResource";
import { authService } from "~/domains/auth/service";
import type { ApiToken, LoginSession } from "~/domains/auth/types";

export interface AccessLedger {
  tokens: ApiToken[];
  /**
   * NOT REVOKED, and not "still valid".
   *
   * The query behind it filters on `revoked` and has never looked at `expires_at`, so an expired
   * token is counted. The expiry is in the table, which is where a reader can see for themselves.
   */
  notRevoked: number;
  sessions: LoginSession[];
}

/** THREE reads, fired together: none of them needs another's answer. */
export function useAccessLedger(userId: number): Resource<AccessLedger> {
  return useResource(async () => {
    const [tokens, active, sessions] = await Promise.all([
      authService.tokensOf(userId),
      authService.activeTokensOf(userId),
      authService.sessionsOf(userId),
    ]);
    return { tokens, notRevoked: active.length, sessions };
  }, [userId]);
}
