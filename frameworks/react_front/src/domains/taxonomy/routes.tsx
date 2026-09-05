/**
 * The taxonomy routes. Four, and the two absences are arguments: there is no update or delete of a
 * tag, because a tag is a NAME that rows point at — renaming one rewrites what every post carrying
 * it says, and deleting one silently unfiles them.
 */

import { defineDomain } from "~/core/routing/domain";
import { PostTagsPage } from "~/domains/taxonomy/pages/PostTagsPage";
import { TagCreatePage } from "~/domains/taxonomy/pages/TagCreatePage";
import { TagFilterPage } from "~/domains/taxonomy/pages/TagFilterPage";
import { TagListPage } from "~/domains/taxonomy/pages/TagListPage";
import { TagTreePage } from "~/domains/taxonomy/pages/TagTreePage";

export const taxonomyRoutes = defineDomain("/tags", {
  list: { segment: "", element: <TagListPage />, nav: "Tags" },
  create: { segment: "new", element: <TagCreatePage />, nav: "New tag" },
  detail: { segment: "post/:postId", element: <PostTagsPage /> },
  filter: { segment: "filter", element: <TagFilterPage />, nav: "Filter posts" },
  tree: { segment: ":tagId/tree", element: <TagTreePage /> },
});
