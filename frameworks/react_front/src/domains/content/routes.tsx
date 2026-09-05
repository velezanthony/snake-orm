/**
 * The content routes. The mirror of `apps/content/web_urls.py`.
 */

import { defineDomain } from "~/core/routing/domain";
import { ContentDetailPage } from "~/domains/content/pages/ContentDetailPage";
import { ContentListPage } from "~/domains/content/pages/ContentListPage";

export const contentRoutes = defineDomain("/content", {
  list: { segment: "", element: <ContentListPage />, nav: "Post histories" },
  detail: { segment: ":postId", element: <ContentDetailPage /> },
});
