/**
 * The accounts pages, as HOOKS: the reads composed and flattened, so a page only paints.
 *
 * This is the mirror of `apps/accounts/viewmodels.py`, and it is the piece the client was missing.
 * Django's view does not compose anything — it calls `viewmodels.role_directory(session)` and hands
 * the result to a template — and the reason is stated across 3,686 lines of that layer: how many
 * statements a page costs, and in what order, is a question about the DOMAIN. Leaving it inside the
 * component put it back in the template, which is exactly what these demos took out.
 *
 * What a hook here owns: which reads a page needs, whether they can go together, and the flat shape
 * that comes out. What it does NOT own: anything about how it looks.
 */

import { useResource, type Resource } from "~/core/hooks/useResource";
import { accountsService } from "~/domains/accounts/service";
import type { Role, UserStats } from "~/domains/accounts/types";

export interface RoleDirectory {
  roles: Role[];
  people: UserStats[];
}

/**
 * TWO statements, and neither grows per row — the same two the SSR page runs.
 *
 * They go in ONE round trip because neither needs the other's answer; awaiting them in sequence
 * would make the page two trips deep for nothing. "Who holds what" is deliberately absent: asking it
 * here would be one query per person, which is why the grants live on the page behind each name.
 */
export function useRoleDirectory(): Resource<RoleDirectory> {
  return useResource(async () => {
    const [roles, directory] = await Promise.all([
      accountsService.roles(),
      accountsService.directory(),
    ]);
    return { roles, people: directory.users };
  }, []);
}

/** One person's grants, and the revoke that re-reads rather than splicing the row out locally. */
export function useUserGrants(userId: number) {
  const grants = useResource(() => accountsService.rolesOf(userId), [userId]);
  return {
    grants,
    revoke: async (roleId: number) => {
      await accountsService.revokeRole(userId, roleId);
      // The server decides the grant is gone. A list edited optimistically is a list that can
      // disagree with it, and nothing on screen would say which one is right.
      grants.reload();
    },
  };
}
