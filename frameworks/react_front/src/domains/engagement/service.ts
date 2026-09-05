/**
 * Engagement: where a database TRIGGER becomes visible.
 *
 * Recording a visit answers with a row REFRESHED from the database, because the counter was moved
 * by the engine underneath the object the handler was holding. It is the one figure on the demo no
 * page could work out for itself, and the reason this domain is not just another table.
 */

import { exportUrl, request, requestList } from "~/core/http/client";
import type { Comment, Reaction, Visit } from "~/domains/engagement/types";

export const engagementService = {
  comments: (postId: number) =>
    requestList<Comment>(`/api/engagement/posts/${postId}/comments`),

  reactions: (postId: number) =>
    requestList<Reaction>(`/api/engagement/posts/${postId}/reactions`),

  visits: (postId: number) => requestList<Visit>(`/api/engagement/posts/${postId}/visits`),

  /**
   * POST on the same path: records one visit, and the answer carries the counter the TRIGGER moved.
   *
   * `visit_count` is a TOP-LEVEL field and not something folded into the visit, because it is a fact
   * about the POST and not about the row that was just written. What comes back is what the engine
   * says the counter now is — the only place that number exists.
   */
  recordVisit: (postId: number) =>
    request<{ visit: Visit; visit_count: number }>(`/api/engagement/posts/${postId}/visits`, {
      method: "POST",
    }),

  exportUrl: () => exportUrl("/api/engagement/visits/export"),
};
