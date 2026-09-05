/**
 * Content: the domain that asks for the same table twice on purpose.
 *
 * `history` DEFERS the body — every column except the one the size of an article — and `revisions`
 * brings the bodies. The difference between those two calls is the section's whole point, which is
 * why they are two methods here and not one with a flag.
 */

import { request, requestList } from "~/core/http/client";
import type { Attachment, Revision } from "~/domains/content/types";

export const contentService = {
  /** The timeline, with the bodies LEFT BEHIND. */
  history: (postId: number) =>
    requestList<Revision>(`/api/content/posts/${postId}/history`),

  /** The same rows WITH their bodies. */
  revisions: (postId: number) =>
    requestList<Revision>(`/api/content/posts/${postId}/revisions`),

  attachments: (postId: number) =>
    requestList<Attachment>(`/api/content/posts/${postId}/attachments`),

  removeAttachment: (attachmentId: number) =>
    request<{ removed: boolean }>(`/api/content/attachments/${attachmentId}`, { method: "DELETE" }),
};
