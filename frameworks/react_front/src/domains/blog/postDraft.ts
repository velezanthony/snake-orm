/**
 * Reading a post out of a submitted form. ONE reader, so the create page and the edit page cannot
 * disagree about what a post is made of.
 *
 * Separate from `PostForm` because that file exports a component, and a module that exports both
 * breaks Fast Refresh for all of it.
 */

import * as fields from "~/core/lib/form";
import type { PostDraft } from "~/domains/blog/service";

export function readPostDraft(form: HTMLFormElement): PostDraft {
  const data = new FormData(form);
  return {
    title: fields.text(data, "title"),
    body: fields.text(data, "body"),
    published: fields.flag(data, "published"),
  };
}
