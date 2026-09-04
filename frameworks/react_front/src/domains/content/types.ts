/**
 * The content domain's shapes: what comes BACK. What goes out lives in `service.ts`.
 *
 * The domain asks for the same table twice on purpose, and `Revision` is the row of both reads — the
 * difference is not the shape, it is whether the body travelled. That is why `body` is optional here
 * rather than there being two interfaces: two would say the timeline and the revisions are different
 * things, and the section's whole point is that they are the same rows asked for differently.
 */

export interface Revision {
  id: number;
  post_id: number;
  edited_at: string;
  /** Absent from the timeline on purpose — that read DEFERS it. Present in `revisions`. */
  body?: string;
}

export interface Attachment {
  id: number;
  post_id: number;
  filename: string;
  url: string;
  size_bytes: number;
}
