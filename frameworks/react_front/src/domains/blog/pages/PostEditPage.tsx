/**
 * The edit form, filled from the post it is editing.
 *
 * The fields are UNCONTROLLED with a `defaultValue`, which only works because the form is not
 * mounted until the post has arrived — `DataState` holds it back. Mounting the inputs empty and
 * filling them later would need controlled state, and would fight anything the reader had already
 * typed.
 */

import { useNavigate, useParams } from "react-router";

import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { Button, ButtonLink } from "@atoms/Button";
import { Card, CardForm } from "@molecules/Card";
import { FormActions } from "@molecules/FormActions";
import { useAction } from "~/core/hooks/useAction";
import { PostFields } from "~/domains/blog/pages/PostForm";
import { readPostDraft } from "~/domains/blog/postDraft";
import { blogWrites, usePost } from "~/domains/blog/viewmodels";

export function PostEditPage() {
  const postId = Number(useParams().postId);
  const navigate = useNavigate();
  const post = usePost(postId);

  const save = useAction(async (form: HTMLFormElement) => {
    await blogWrites.update(postId, readPostDraft(form));
    await navigate(href("blog.detail", { postId: postId }));
  });

  return (
    <>
      <PageHead title="Edit post" lede="The API gates this to the author: somebody else's post comes back 403." />

      {save.error !== null ? <Alert kind="error">{save.error}</Alert> : null}

      <DataState resource={post} loading="Loading the post…">
        {(data) => (
          <Card className="max-w-2xl">
            <CardForm onSubmit={(form) => void save.run(form)}>
              <PostFields post={data} />
              <FormActions>
                <Button type="submit" disabled={save.pending}>
                  {save.pending ? "Saving…" : "Save"}
                </Button>
                <ButtonLink to={href("blog.detail", { postId: postId })}>Cancel</ButtonLink>
              </FormActions>
            </CardForm>
          </Card>
        )}
      </DataState>
    </>
  );
}
