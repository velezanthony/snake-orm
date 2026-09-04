/**
 * Where a tag sits.
 *
 * A taxonomy is a hierarchy — the word means nothing else — and this is the page that draws one.
 * The path back to the root and the section hanging underneath are two statements, and neither of
 * them grows when the tree grows a level: a `WITH RECURSIVE` follows a chain whose length nobody
 * knows in advance. The same screen without it is one query per level, twice over.
 */

import { Link, useParams } from "react-router";

import { href } from "~/config/href";

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { ButtonLink } from "@atoms/Button";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { useTagTree } from "~/domains/taxonomy/viewmodels";

export function TagTreePage() {
  const tagId = Number(useParams().tagId);
  const tree = useTagTree(tagId);

  return (
    <>
      <PageHead
        title={`Tag #${tagId}`}
        lede="A taxonomy is a hierarchy, and this is the page that draws one. The path back to the root and the section hanging underneath are two statements, and neither of them grows when the tree grows a level."
        actions={
          <ButtonLink size="sm" to={href("taxonomy.list")}>
            ← Every tag
          </ButtonLink>
        }
      />

      <DataState resource={tree} loading="Walking the tree…">
        {({ breadcrumb, branch }) => (
          <>
            <Card className="mb-6">
              <CardHead title="Path to the root" sub="One WITH RECURSIVE upwards, whatever the depth." />
              <CardBody>
                {breadcrumb.length === 0 ? (
                  <span className="muted">This tag is a root.</span>
                ) : (
                  <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-2">
                    {breadcrumb.map((tag, index) => (
                      <span key={tag.id} className="flex items-center gap-2">
                        {index > 0 ? <span className="muted">›</span> : null}
                        <Link className="font-medium text-ink-900 hover:text-brand-700" to={href("taxonomy.tree", { tagId: tag.id })}>
                          {tag.name}
                        </Link>
                      </span>
                    ))}
                  </nav>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHead title="The section underneath" sub="One WITH RECURSIVE downwards, same statement count." />
              <DataTable
                bare
                label="Descendants"
                caption="Every tag hanging below this one, however deep."
                rows={branch}
                rowKey={(tag) => tag.id}
                empty="nothing hangs below this one"
                columns={[
                  { header: "Tag", cell: (tag) => <span className="font-medium text-ink-900">{tag.name}</span> },
                  { header: "Parent", cell: (tag) => <span className="muted">{tag.parent_id ?? "—"}</span> },
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
          </>
        )}
      </DataState>
    </>
  );
}
