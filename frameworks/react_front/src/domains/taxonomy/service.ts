/** Taxonomy: tags, their groups, their tree, and the N-N against posts resolved over the bridge. */

import { query, request, requestList } from "~/core/http/client";
import type { Post } from "~/domains/blog/types";
import type { Tag, TagGroup, TagTree } from "~/domains/taxonomy/types";

export const taxonomyService = {
  groups: () => requestList<TagGroup>("/api/taxonomy/groups"),

  tags: () => requestList<Tag>("/api/taxonomy/tags"),

  /** The self-referencing walk: ONE `WITH RECURSIVE` per half, whatever the depth of the tree. */
  tree: (tagId: number) => request<TagTree>(`/api/taxonomy/tags/${tagId}/tree`),

  /**
   * The page this domain exists for, and ONE route answering two different questions.
   *
   * With `tagIds` alone the engine is asked to INTERSECT: requiring two tags is a condition on two
   * DIFFERENT bridge rows, so `tag_id = A AND tag_id = B` matches nothing and no WHERE expresses
   * it. Fewer than two tags is a 400 rather than a shortcut, because "the posts of one tag" is a
   * different question with an operation of its own.
   *
   * Add `without` and it becomes an EXCEPT instead: the first tag is the base and the named one is
   * subtracted, which states the difference rather than handing the planner a negated subquery.
   */
  filterPosts: (tagIds: number[], without?: number) =>
    requestList<Post>(`/api/taxonomy/posts${query({ tags: tagIds.join(","), without })}`),

  tagsOf: (postId: number) => requestList<Tag>(`/api/taxonomy/posts/${postId}/tags`),

  createTag: (body: { name: string; group_id: number; parent_id?: number | null }) =>
    request<Tag>("/api/taxonomy/tags", { method: "POST", body }),

  /**
   * Ticking a box. `get_or_create` underneath, which is what made tagging IDEMPOTENT: submitting
   * the same box twice leaves ONE bridge row instead of two.
   */
  tagPost: (postId: number, tagId: number) =>
    request<{ post_id: number; tag_id: number }>(`/api/taxonomy/posts/${postId}/tags`, {
      method: "POST",
      body: { tag_id: tagId },
    }),

  /** Unticking. Asks `exists` and then deletes by the PAIR, never loading the row it discards. */
  untag: (postId: number, tagId: number) =>
    request<{ removed: boolean }>(`/api/taxonomy/posts/${postId}/tags/${tagId}`, {
      method: "DELETE",
    }),
};
