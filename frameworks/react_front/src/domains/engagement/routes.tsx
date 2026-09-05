/**
 * The engagement routes. There is no `export` entry: what that link reaches is a streamed CSV, so
 * the sidebar points it straight at the API — a page that rendered a file would be a page about
 * nothing.
 */

import { defineDomain } from "~/core/routing/domain";
import { EngagementSheetPage } from "~/domains/engagement/pages/EngagementSheetPage";
import { TrafficBoardPage } from "~/domains/engagement/pages/TrafficBoardPage";

export const engagementRoutes = defineDomain("/engagement", {
  list: { segment: "", element: <TrafficBoardPage />, nav: "Traffic board" },
  detail: { segment: ":postId", element: <EngagementSheetPage /> },
});
