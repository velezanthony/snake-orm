/**
 * The blog's shapes. `Post` carries the counter a TRIGGER keeps, which is the one figure no client can work out for itself.
 */

import type { User } from "~/domains/accounts/types";

export interface Post {
  id: number;
  title: string;
  body: string;
  published: boolean;
  author_id: number;
  /**
   * The counter a database TRIGGER keeps.
   *
   * It is a plain column on the post, which is the entire reason the traffic board costs ONE
   * statement whatever the size of the visits table — and the reason this client can draw that
   * board from the blog's own listing instead of counting visits per row.
   */
  visit_count: number;
  author?: User;
}
