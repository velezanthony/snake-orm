/**
 * Every post with its author. `include(Post.author)` is ONE join, so the panel underneath shows one
 * query for a table with three hundred rows in it.
 *
 * The `mine` column is decided here because the API does not send it, and that is not a gap:
 * `author_id` and the logged-in user are both already on the page, and asking the server to compute
 * a boolean out of two numbers it already handed over would be a round trip for nothing.
 */

import { href } from "~/config/href";
import { StateBadge } from "@atoms/Badge";
import { ButtonLink } from "@atoms/Button";
import { Code, Empty } from "@atoms/Text";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { useAuth } from "~/domains/auth/useAuth";
import { usePosts } from "~/domains/blog/viewmodels";

export function PostListPage() {
  const { user } = useAuth();
  const posts = usePosts();

  return (
    <>
      <PageHead
        title="Posts"
        lede={
          <>
            Listed with <Code>include(Post.author)</Code>: a single JOIN, no N+1. The debug panel at
            the end of the page is fed by the same response.
          </>
        }
      />

      <DataState resource={posts} loading="Loading posts…">
        {({ posts: rows }) =>
          rows.length === 0 ? (
            <Empty>No posts yet.</Empty>
          ) : (
            <DataTable
              label="Posts"
              caption="Every post, with its author, state and the actions you may take."
              rows={rows}
              rowKey={(post) => post.id}
              empty="no posts"
              columns={[
                {
                  header: "Title",
                  cell: (post) => (
                    <a className="font-medium text-ink-900 hover:text-brand-700" href={href("blog.detail", { postId: post.id })}>
                      {post.title}
                    </a>
                  ),
                },
                { header: "Author", cell: (post) => <span className="text-ink-600">{post.author?.username ?? `#${post.author_id}`}</span> },
                { header: "State", cell: (post) => <StateBadge on={post.published} yes="Published" no="Draft" /> },
                {
                  header: "Actions",
                  align: "right",
                  cell: (post) =>
                    user !== null && user.id === post.author_id ? (
                      <div className="inline-flex gap-2">
                        <ButtonLink size="sm" to={href("blog.update", { postId: post.id })}>
                          Edit
                        </ButtonLink>
                        <ButtonLink size="sm" variant="danger" to={href("blog.delete", { postId: post.id })}>
                          Delete
                        </ButtonLink>
                      </div>
                    ) : null,
                },
              ]}
            />
          )
        }
      </DataState>
    </>
  );
}
