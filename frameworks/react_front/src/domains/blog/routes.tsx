/**
 * The blog's routes. The mirror of `apps/blog/urls.py`, mounted at the root as Django mounts it.
 *
 * The prefix is `"/"` because this domain IS the landing page — `config/urls.py` includes
 * `apps.blog.urls` at the empty path for the same reason.
 */

import { defineDomain } from "~/core/routing/domain";
import { PostCreatePage } from "~/domains/blog/pages/PostCreatePage";
import { PostDeletePage } from "~/domains/blog/pages/PostDeletePage";
import { PostDetailPage } from "~/domains/blog/pages/PostDetailPage";
import { PostEditPage } from "~/domains/blog/pages/PostEditPage";
import { PostListPage } from "~/domains/blog/pages/PostListPage";

export const blogRoutes = defineDomain("/", {
  list: { segment: "", element: <PostListPage />, nav: "Posts" },
  detail: { segment: "posts/:postId", element: <PostDetailPage /> },
  create: { segment: "posts/new", element: <PostCreatePage />, nav: "New post", gated: true },
  update: { segment: "posts/:postId/edit", element: <PostEditPage />, gated: true },
  delete: { segment: "posts/:postId/delete", element: <PostDeletePage />, gated: true },
});
