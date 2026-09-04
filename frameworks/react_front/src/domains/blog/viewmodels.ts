/**
 * The blog pages as hooks. The mirror of the reads `apps/blog/views.py` makes.
 */

import { useResource, type Resource } from "~/core/hooks/useResource";
import { blogService, type PostDraft } from "~/domains/blog/service";
import type { Post } from "~/domains/blog/types";

/** `include(Post.author)`: a single JOIN, no N+1, whatever the number of rows. */
export function usePosts(): Resource<{ posts: Post[] }> {
  return useResource(() => blogService.list(), []);
}

export function usePost(postId: number): Resource<Post> {
  return useResource(() => blogService.get(postId), [postId]);
}

/** The three writes, each one a use case of its own — never a single button covering all three. */
export const blogWrites = {
  create: (draft: PostDraft) => blogService.create(draft),
  update: (postId: number, draft: PostDraft) => blogService.update(postId, draft),
  remove: (postId: number) => blogService.remove(postId),
};
