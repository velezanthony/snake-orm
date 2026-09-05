/**
 * The grants of one person, and the tag screen with different nouns.
 *
 * ONE BOX PER REQUEST, which is the SSR page's argument: revoking is its own call, so `revoke_role`
 * stays visible as itself. A submit-everything form would collapse it into "make the rows match this
 * list", which is a third operation neither surface offers.
 *
 * Only the revoke half is here, and that is the API rather than a decision of this page: the accounts
 * resource registers a DELETE for a grant and no POST to create one.
 */

import { useParams } from "react-router";

import { href } from "~/config/href";
import { Button, ButtonLink } from "@atoms/Button";
import { Alert } from "@molecules/Alert";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { useAction } from "~/core/hooks/useAction";
import { useUserGrants } from "~/domains/accounts/viewmodels";

export function AccountsDetailPage() {
  const userId = Number(useParams().userId);
  const { grants, revoke } = useUserGrants(userId);
  const revoking = useAction(revoke);

  return (
    <>
      <PageHead
        title={`Roles of user ${userId}`}
        lede="The tag screen with different nouns, and deliberately so: granting a role is the same shape as putting a tag on a post, over the same pair of writes on a bridge table. One box per request, so revoke_role stays visible as itself."
        actions={
          <ButtonLink size="sm" to={href("accounts.list")}>
            ← Everybody
          </ButtonLink>
        }
      />

      {revoking.error !== null ? <Alert kind="error">{revoking.error}</Alert> : null}

      <DataState resource={grants} loading="Reading the grants…">
        {(roles) => (
          <DataTable
            label="Grants"
            caption="Every role this person holds, with the one operation the API offers on it."
            rows={roles}
            rowKey={(role) => role.id}
            empty="this person holds nothing"
            columns={[
              { header: "Role", cell: (role) => <span className="font-medium text-ink-900">{role.name}</span> },
              {
                header: "Actions",
                align: "right",
                cell: (role) => (
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={revoking.pending}
                    onClick={() => void revoking.run(role.id)}
                  >
                    Revoke
                  </Button>
                ),
              },
            ]}
          />
        )}
      </DataState>
    </>
  );
}
