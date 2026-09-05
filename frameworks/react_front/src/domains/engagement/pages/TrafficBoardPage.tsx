/**
 * One statement for the whole board, whatever the size of the visits table.
 */

import { href } from "~/config/href";
import { ButtonAnchor } from "@atoms/Button";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { DescriptionList } from "@molecules/DescriptionList";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { engagementService } from "~/domains/engagement/service";
import { useTrafficBoard } from "~/domains/engagement/viewmodels";

export function TrafficBoardPage() {
  const board = useTrafficBoard();

  return (
    <>
      <PageHead
        title="Traffic board"
        lede="One statement for the whole board, whatever the size of the visits table. The counter is a column on the post, kept by a TRIGGER rather than by this ORM, so a listing of every post costs one query — where counting post.visits per row would be an N+1 over the demo's biggest table."
        actions={
          <ButtonAnchor size="sm" href={engagementService.exportUrl()}>
            Export CSV
          </ButtonAnchor>
        }
      />

      <DataState resource={board} loading="Reading the board…">
        {({ rows, total }) => (
          <>
            <Card className="mb-6">
              <CardHead title="Totals" sub="Both figures are read off rows that had already arrived." />
              <CardBody>
                <DescriptionList rows={[["Posts", rows.length], ["Visits counted", total]]} />
              </CardBody>
            </Card>

            <DataTable
              label="Traffic board"
              caption="Every post with the visits the trigger has counted for it, busiest first."
              rows={rows}
              rowKey={(post) => post.id}
              empty="no posts"
              columns={[
                {
                  header: "Post",
                  cell: (post) => (
                    <a className="font-medium text-ink-900 hover:text-brand-700" href={href("engagement.detail", { postId: post.id })}>
                      {post.title}
                    </a>
                  ),
                },
                { header: "Author", cell: (post) => <span className="muted">{post.author?.username ?? `#${post.author_id}`}</span> },
                { header: "Visits", cell: (post) => post.visit_count },
              ]}
            />
          </>
        )}
      </DataState>
    </>
  );
}
