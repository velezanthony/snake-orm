/**
 * The engagement domain's shapes: what comes BACK. What goes out lives in `service.ts`.
 *
 * Where a database TRIGGER becomes visible: the counter on a post is moved by the engine, not by
 * this client, so `visit_count` is a field of `Post` and never of anything here.
 */

export interface Comment {
  id: number;
  post_id: number;
  author_id: number;
  body: string;
  created_at: string;
}

export interface Reaction {
  id: number;
  post_id: number;
  user_id: number;
  kind: string;
  created_at: string;
}

export interface Visit {
  id: number;
  post_id: number;
  ip: string | null;
  user_agent: string | null;
  visited_at: string;
}
