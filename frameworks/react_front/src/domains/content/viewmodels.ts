/**
 * The content pages as hooks. The mirror of `apps/content/viewmodels.py`.
 *
 * The section's whole subject is that TWO reads of the same table are not the same read, so the
 * composition is the thing worth naming — and naming it here is what keeps the page from looking
 * like it made an arbitrary choice.
 */

import { useResource, type Resource } from "~/core/hooks/useResource";
import { blogService } from "~/domains/blog/service";
import type { Post } from "~/domains/blog/types";
import { contentService } from "~/domains/content/service";
import type { Attachment, Revision } from "~/domains/content/types";

/**
 * The listing is the BLOG's own read, asked here for a different question.
 *
 * Two modules answering "every post with its author" is how two listings start disagreeing about
 * what a post is, which is the shared viewmodel's argument and holds one storey up: this domain
 * calls the blog's service rather than growing one that returns the same rows.
 */
export function usePostHistories(): Resource<{ posts: Post[] }> {
  return useResource(() => blogService.list(), []);
}

export interface PostHistory {
  post: Post;
  /** `defer(PostRevision.body)`: the instants, without the articles behind them. */
  timeline: Revision[];
  /** The SAME rows, WITH their bodies. Two requests because they are two questions. */
  revisions: Revision[];
  attachments: Attachment[];
}

/**
 * FOUR reads, fired together.
 *
 * The timeline and the revisions are kept apart on purpose: on a post edited two hundred times the
 * first costs two hundred instants and the second two hundred copies of an article. Folding them
 * into one would be this client deciding the section's whole point is a detail.
 */
export function usePostHistory(postId: number): Resource<PostHistory> {
  return useResource(async () => {
    const [post, timeline, revisions, attachments] = await Promise.all([
      blogService.get(postId),
      contentService.history(postId),
      contentService.revisions(postId),
      contentService.attachments(postId),
    ]);
    return { post, timeline, revisions, attachments };
  }, [postId]);
}
