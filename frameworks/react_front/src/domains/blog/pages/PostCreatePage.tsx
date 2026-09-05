/** The new-post form. Gated: the route sits behind `RequireAuth`, as `login_required` gates Django's. */

import { useNavigate } from "react-router";

import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { PageHead } from "@molecules/PageHead";
import { Button, ButtonLink } from "@atoms/Button";
import { Card, CardForm } from "@molecules/Card";
import { FormActions } from "@molecules/FormActions";
import { useAction } from "~/core/hooks/useAction";
import { PostFields } from "~/domains/blog/pages/PostForm";
import { readPostDraft } from "~/domains/blog/postDraft";
import { blogWrites } from "~/domains/blog/viewmodels";

export function PostCreatePage() {
  const navigate = useNavigate();

  const create = useAction(async (form: HTMLFormElement) => {
    const post = await blogWrites.create(readPostDraft(form));
    await navigate(href("blog.detail", { postId: post.id }));
  });

  return (
    <>
      <PageHead title="New post" lede="The author is the session's user; the API refuses the write without one." />

      {create.error !== null ? <Alert kind="error">{create.error}</Alert> : null}

      <Card className="max-w-2xl">
        <CardForm onSubmit={(form) => void create.run(form)}>
          <PostFields />
          <FormActions>
            <Button type="submit" disabled={create.pending}>
              {create.pending ? "Publishing…" : "Publish"}
            </Button>
            <ButtonLink to={href("blog.list")}>Cancel</ButtonLink>
          </FormActions>
        </CardForm>
      </Card>
    </>
  );
}
