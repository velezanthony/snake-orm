/**
 * Every tag, under the group it belongs to. TWO statements, and the grouping happens once.
 */

import { href } from "~/config/href";
import { ButtonLink } from "@atoms/Button";
import { Empty } from "@atoms/Text";
import { Card, CardHead } from "@molecules/Card";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { useTagCatalogue } from "~/domains/taxonomy/viewmodels";

export function TagListPage() {
  const catalogue = useTagCatalogue();

  return (
    <>
      <PageHead
        title="Tags"
        lede="Two statements for the whole screen, and neither grows with the number of groups: every tag arrives with its group already joined, and the grouping happens once in the client. Walking group.tags here instead would be this same page at one query per group — an N+1 inside the renderer, where no test counts."
      />

      <DataState resource={catalogue} loading="Reading the taxonomy…">
        {({ groups, tags }) =>
          groups.length === 0 ? (
            <Empty>No groups yet.</Empty>
          ) : (
            groups.map((group) => {
              const inGroup = tags.filter((tag) => tag.group_id === group.id);
              return (
                <Card className="mb-6" key={group.id}>
                  <CardHead title={group.name} sub={`${inGroup.length} tag${inGroup.length === 1 ? "" : "s"}`} />
                  <DataTable
                    bare
                    label={`Tags of ${group.name}`}
                    caption={`Every tag filed under ${group.name}, with where it sits in the tree.`}
                    rows={inGroup}
                    rowKey={(tag) => tag.id}
                    empty="nothing filed here"
                    columns={[
                      { header: "Tag", cell: (tag) => <span className="font-medium text-ink-900">{tag.name}</span> },
                      {
                        header: "Parent",
                        cell: (tag) => (
                          <span className="muted">
                            {tag.parent_id === null ? "—" : (tags.find((t) => t.id === tag.parent_id)?.name ?? `#${tag.parent_id}`)}
                          </span>
                        ),
                      },
                      {
                        header: "Actions",
                        align: "right",
                        cell: (tag) => (
                          <ButtonLink size="sm" to={href("taxonomy.tree", { tagId: tag.id })}>
                            Tree
                          </ButtonLink>
                        ),
                      },
                    ]}
                  />
                </Card>
              );
            })
          )
        }
      </DataState>
    </>
  );
}
