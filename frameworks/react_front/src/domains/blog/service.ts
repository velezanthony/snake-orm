/** The blog: the CRUD every demo opens with. Reads are public; writes are gated to the author. */

import { request } from "~/core/http/client";
import type { UserStats } from "~/domains/accounts/types";
import type { Post } from "~/domains/blog/types";

export interface PostDraft {
  title: string;
  body: string;
  published: boolean;
}

export const blogService = {
  list: () => request<{ posts: Post[] }>("/api/posts"),

  stats: () => request<{ users: UserStats[] }>("/api/posts/stats"),

  get: (postId: number) => request<Post>(`/api/posts/${postId}`),

  create: (draft: PostDraft) => request<Post>("/api/posts", { method: "POST", body: draft }),

  update: (postId: number, draft: Partial<PostDraft>) =>
    request<Post>(`/api/posts/${postId}`, { method: "PATCH", body: draft }),

  remove: (postId: number) => request<{ deleted: boolean }>(`/api/posts/${postId}`, { method: "DELETE" }),
};
