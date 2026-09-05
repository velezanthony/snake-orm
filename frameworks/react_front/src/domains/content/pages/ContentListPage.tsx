/**
 * Pick a post to open its history and its attached files.
 */

import { href } from "~/config/href";
import { ButtonLink } from "@atoms/Button";
import { StateBadge } from "@atoms/Badge";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { usePostHistories } from "~/domains/content/viewmodels";

export function ContentListPage() {
  const posts = usePostHistories();

  return (
    <>
      <PageHead
        title="Post histories"
        lede="Pick a post to open its history and its attached files. The listing itself is one statement with the authors already joined — it is the blog's own read, asked here for a different question, because two modules answering “every post with its author” is how two listings start disagreeing about what a post is."
      />

      <DataState resource={posts} loading="Reading the posts…">
        {({ posts: rows }) => (
          <DataTable
            label="Post histories"
            caption="Every post, as a way into its revision history."
            rows={rows}
            rowKey={(post) => post.id}
            empty="no posts"
            columns={[
              {
                header: "Title",
                cell: (post) => (
                  <a className="font-medium text-ink-900 hover:text-brand-700" href={href("content.detail", { postId: post.id })}>
                    {post.title}
                  </a>
                ),
              },
              { header: "Author", cell: (post) => <span className="muted">{post.author?.username ?? `#${post.author_id}`}</span> },
              { header: "State", cell: (post) => <StateBadge on={post.published} yes="Published" no="Draft" /> },
              {
                header: "Actions",
                align: "right",
                cell: (post) => (
                  <ButtonLink size="sm" to={href("content.detail", { postId: post.id })}>
                    History
                  </ButtonLink>
                ),
              },
            ]}
          />
        )}
      </DataState>
    </>
  );
}
