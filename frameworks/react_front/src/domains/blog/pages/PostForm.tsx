/**
 * The three fields a post is made of, shared by the create and the edit page — the same split
 * `templates/blog/_form.html` makes, for the same reason: two forms that drift are two forms that
 * accept different things.
 */

import { Check, Field, Input, Textarea } from "@atoms/Field";
import type { Post } from "~/domains/blog/types";

export function PostFields({ post }: { post?: Post }) {
  return (
    <>
      <Field id="title" label="Title">
        <Input type="text" id="title" name="title" defaultValue={post?.title ?? ""} autoFocus />
      </Field>

      <Field id="body" label="Body">
        <Textarea id="body" name="body" rows={6} defaultValue={post?.body ?? ""} />
      </Field>

      <Check name="published" defaultChecked={post?.published ?? false}>
        Published
      </Check>
    </>
  );
}
