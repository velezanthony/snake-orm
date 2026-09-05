/**
 * One post's comments, reactions and visits.
 *
 * THE COUNTER BESIDE THE TITLE IS THE NUMBER THE DATABASE HOLDS, not the length of the list below
 * it. `visit_count` is moved by a trigger underneath the object the request was holding, so
 * recording a visit answers with the counter REFRESHED from the engine — the one figure in the demo
 * that nothing in this client is in a position to work out.
 */

import { useParams } from "react-router";

import { href } from "~/config/href";
import { Badge } from "@atoms/Badge";
import { Button, ButtonLink } from "@atoms/Button";
import { Alert } from "@molecules/Alert";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { useAction } from "~/core/hooks/useAction";
import { useEngagementSheet } from "~/domains/engagement/viewmodels";

export function EngagementSheetPage() {
  const postId = Number(useParams().postId);
  const { sheet, counted, recordVisit } = useEngagementSheet(postId);
  const visit = useAction(recordVisit);

  return (
    <DataState resource={sheet} loading="Reading the sheet…">
      {({ post, comments, reactions, visits }) => (
        <>
          <PageHead
            title={post.title}
            lede="The counter beside the title is the number the database holds, not the length of the list below it. visit_count is moved by a trigger underneath the object this page was holding, so recording a visit answers with a row refreshed from the engine — the one figure in the demo that nothing in this client is in a position to work out."
            actions={
              <ButtonLink size="sm" to={href("engagement.list")}>
                ← The board
              </ButtonLink>
            }
          />

          {visit.error !== null ? <Alert kind="error">{visit.error}</Alert> : null}

          <Card className="mb-6">
            <CardHead
              title="Visits"
              sub="The button records one and shows you what the engine came back with."
              aside={<Badge tone="ok">{counted ?? post.visit_count} counted</Badge>}
            />
            <CardBody>
              <Button disabled={visit.pending} onClick={() => void visit.run()}>
                {visit.pending ? "Recording…" : "Record a visit"}
              </Button>
            </CardBody>
          </Card>

          <Card className="mb-6">
            <CardHead title="Comments" sub={`${comments.length} on this post.`} />
            <DataTable
              bare
              label="Comments"
              caption="Every comment on this post."
              rows={comments}
              rowKey={(comment) => comment.id}
              empty="nobody has said anything"
              columns={[
                { header: "Author", cell: (c) => <span className="muted">#{c.author_id}</span> },
                { header: "Comment", cell: (c) => <span className="text-ink-900">{c.body}</span> },
                { header: "When", cell: (c) => <span className="muted">{c.created_at}</span> },
              ]}
            />
          </Card>

          <Card className="mb-6">
            <CardHead title="Reactions" sub={`${reactions.length} on this post.`} />
            <DataTable
              bare
              label="Reactions"
              caption="Every reaction on this post, with who left it."
              rows={reactions}
              rowKey={(reaction) => reaction.id}
              empty="no reactions"
              columns={[
                { header: "Kind", cell: (r) => <span className="font-medium text-ink-900">{r.kind}</span> },
                { header: "User", cell: (r) => <span className="muted">#{r.user_id}</span> },
                { header: "When", cell: (r) => <span className="muted">{r.created_at}</span> },
              ]}
            />
          </Card>

          <Card>
            <CardHead
              title="The visits themselves"
              sub="The rows. Their number and the counter above can differ — the counter is the engine's."
            />
            <DataTable
              bare
              label="Visits"
              caption="Every recorded visit to this post."
              rows={visits}
              rowKey={(row) => row.id}
              empty="nobody has been here"
              columns={[
                { header: "#", cell: (v) => <span className="muted">{v.id}</span> },
                { header: "Address", cell: (v) => <span className="muted">{v.ip ?? "—"}</span> },
                { header: "When", cell: (v) => <span className="muted">{v.visited_at}</span> },
              ]}
            />
          </Card>
        </>
      )}
    </DataState>
  );
}
