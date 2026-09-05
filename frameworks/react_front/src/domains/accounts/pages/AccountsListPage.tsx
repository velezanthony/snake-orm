/**
 * Roles and people. The page PAINTS and nothing else: which reads it needs, and whether they can go
 * together, is `useRoleDirectory`'s business.
 */

import { href } from "~/config/href";
import { ButtonLink } from "@atoms/Button";
import { Card, CardHead } from "@molecules/Card";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { useRoleDirectory } from "~/domains/accounts/viewmodels";

export function AccountsListPage() {
  const board = useRoleDirectory();

  return (
    <>
      <PageHead
        title="Roles & people"
        lede="Two statements, and neither of them grows per row. The roles are this domain's; the people come from the blog's own typed aggregate, which counts in the engine. Asking “who holds what” from this table instead would be one query per person — so the grants live on the page behind each name."
      />

      <DataState resource={board} loading="Reading the directory…">
        {({ roles, people }) => (
          <>
            <Card className="mb-6">
              <CardHead
                title="Roles"
                sub="There is no page to rename or delete one: a role is a NAME that grants point at, so renaming it rewrites what every holder is entitled to."
              />
              <DataTable
                bare
                label="Roles"
                caption="Every role in the catalogue."
                rows={roles}
                rowKey={(role) => role.id}
                empty="no roles"
                columns={[
                  { header: "#", cell: (role) => <span className="muted">{role.id}</span> },
                  { header: "Name", cell: (role) => <span className="font-medium text-ink-900">{role.name}</span> },
                ]}
              />
            </Card>

            <Card>
              <CardHead title="People" sub="Open a name to see and change what they hold." />
              <DataTable
                bare
                label="People"
                caption="Everybody in the demo, with what the engine counted for them."
                rows={people}
                rowKey={(person) => person.id}
                empty="nobody yet"
                columns={[
                  { header: "User", cell: (person) => <span className="font-medium text-ink-900">{person.username}</span> },
                  { header: "Posts", cell: (person) => <span className="muted">{person.post_count}</span> },
                  {
                    header: "Grants",
                    align: "right",
                    cell: (person) => (
                      <ButtonLink size="sm" to={href("accounts.detail", { userId: person.id })}>
                        Roles
                      </ButtonLink>
                    ),
                  },
                ]}
              />
            </Card>
          </>
        )}
      </DataState>
    </>
  );
}
