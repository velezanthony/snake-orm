/**
 * The two panels below read the SAME TABLE and are not the same read.
 *
 * The timeline is a `defer(PostRevision.body)` — every column except the one that is the size of an
 * article — and the revisions under it are the full rows. Which of the two a page asks for is the
 * section's whole subject, and `usePostHistory` is where that choice is made and argued.
 */

import { useParams } from "react-router";

import { href } from "~/config/href";
import { ButtonLink } from "@atoms/Button";
import { Card, CardHead } from "@molecules/Card";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { usePostHistory } from "~/domains/content/viewmodels";

export function ContentDetailPage() {
  const postId = Number(useParams().postId);
  const sheet = usePostHistory(postId);

  return (
    <DataState resource={sheet} loading="Reading the history…">
      {({ post, timeline, revisions, attachments }) => (
        <>
          <PageHead
            title={post.title}
            lede="The two panels below read the same table and are not the same read. The timeline DEFERS the body — every column except the one that is the size of an article — and the revisions under it are the full rows."
            actions={
              <ButtonLink size="sm" to={href("content.list")}>
                ← Every history
              </ButtonLink>
            }
          />

          <Card className="mb-6">
            <CardHead title="Timeline" sub="defer(PostRevision.body): the instants, without the articles behind them." />
            <DataTable
              bare
              label="Timeline"
              caption="When this post was edited, without loading what it said."
              rows={timeline}
              rowKey={(revision) => revision.id}
              empty="never edited"
              columns={[
                { header: "#", cell: (revision) => <span className="muted">{revision.id}</span> },
                { header: "Edited", cell: (revision) => revision.edited_at },
              ]}
            />
          </Card>

          <Card className="mb-6">
            <CardHead title="Revisions" sub="The same rows, WITH their bodies. The difference is the page." />
            <DataTable
              bare
              label="Revisions"
              caption="Every revision of this post, with what it said."
              rows={revisions}
              rowKey={(revision) => revision.id}
              empty="never edited"
              columns={[
                { header: "#", cell: (revision) => <span className="muted">{revision.id}</span> },
                { header: "Body", cell: (revision) => <span className="whitespace-pre-line text-ink-800">{revision.body ?? "—"}</span> },
              ]}
            />
          </Card>

          <Card>
            <CardHead title="Attachments" sub="The files hanging off this post." />
            <DataTable
              bare
              label="Attachments"
              caption="Every file attached to this post."
              rows={attachments}
              rowKey={(attachment) => attachment.id}
              empty="nothing attached"
              columns={[
                { header: "#", cell: (a) => <span className="muted">{a.id}</span> },
                { header: "Filename", cell: (a) => <span className="font-medium text-ink-900">{a.filename}</span> },
                { header: "Size", cell: (a) => <span className="muted">{a.size_bytes}</span> },
              ]}
            />
          </Card>
        </>
      )}
    </DataState>
  );
}
