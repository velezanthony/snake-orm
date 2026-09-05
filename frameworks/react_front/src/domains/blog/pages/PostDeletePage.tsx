/**
 * The confirmation page, and it is a PAGE rather than a `window.confirm`.
 *
 * The three demos give deleting a screen of its own, and it earns one: the thing about to be
 * destroyed is named on it, and the URL is somewhere you can arrive from a link and leave without
 * having pressed anything.
 */

import { useNavigate, useParams } from "react-router";

import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { DataState } from "@organisms/DataState";
import { Button, ButtonLink } from "@atoms/Button";
import { ArticleCard, CardBody, CardFoot, CardHead } from "@molecules/Card";
import { useAction } from "~/core/hooks/useAction";
import { blogWrites, usePost } from "~/domains/blog/viewmodels";

export function PostDeletePage() {
  const postId = Number(useParams().postId);
  const navigate = useNavigate();
  const post = usePost(postId);

  const remove = useAction(async () => {
    await blogWrites.remove(postId);
    await navigate(href("blog.list"), { replace: true });
  });

  return (
    <DataState resource={post} loading="Loading the post…">
      {(data) => (
        <ArticleCard className="max-w-lg">
          <CardHead title={<span className="text-xl">Delete post</span>} />
          <CardBody className="text-ink-600">
            {remove.error !== null ? <Alert kind="error">{remove.error}</Alert> : null}
            Are you sure you want to delete <strong className="text-ink-900">{data.title}</strong>? This
            cannot be undone.
          </CardBody>
          <CardFoot>
            <Button variant="danger" disabled={remove.pending} onClick={() => void remove.run()}>
              {remove.pending ? "Deleting…" : "Yes, delete it"}
            </Button>
            <ButtonLink to={href("blog.detail", { postId: postId })}>Cancel</ButtonLink>
          </CardFoot>
        </ArticleCard>
      )}
    </DataState>
  );
}
