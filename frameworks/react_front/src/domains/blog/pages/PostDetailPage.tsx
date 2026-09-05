/** One post with its author, and the two owner actions the SSR card carries in its footer. */

import { Link, useParams } from "react-router";

import { href } from "~/config/href";

import { useAuth } from "~/domains/auth/useAuth";
import { DataState } from "@organisms/DataState";
import { StateBadge } from "@atoms/Badge";
import { ButtonLink } from "@atoms/Button";
import { ArticleCard, CardBody, CardFoot, CardHead } from "@molecules/Card";
import { usePost } from "~/domains/blog/viewmodels";

export function PostDetailPage() {
  const postId = Number(useParams().postId);
  const { user } = useAuth();
  const post = usePost(postId);

  return (
    <>
      <Link className="muted hover:text-ink-800" to={href("blog.list")}>
        ← Back to posts
      </Link>

      <DataState resource={post} loading="Loading the post…">
        {(data) => {
          const mine = user !== null && user.id === data.author_id;
          return (
            <ArticleCard className="mt-4">
              <CardHead
                title={<span className="text-xl">{data.title}</span>}
                sub={`by ${data.author?.username ?? `#${data.author_id}`}`}
                aside={<StateBadge on={data.published} yes="Published" no="Draft" />}
              />

              {/* `whitespace-pre-line` and not a split into paragraphs: the SSR page uses
                  `linebreaksbr`, which is the same decision — the body is text, not markup. */}
              <CardBody className="whitespace-pre-line text-ink-800">{data.body}</CardBody>

              {mine ? (
                <CardFoot>
                  <ButtonLink to={href("blog.update", { postId: data.id })}>Edit</ButtonLink>
                  <ButtonLink variant="danger" to={href("blog.delete", { postId: data.id })}>
                    Delete
                  </ButtonLink>
                </CardFoot>
              ) : null}
            </ArticleCard>
          );
        }}
      </DataState>
    </>
  );
}
