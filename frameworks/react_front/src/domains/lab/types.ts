/**
 * The lab domain's shapes: what comes BACK.
 *
 * Five of the six endpoints answer the same `sections` payload, which lives in `core/http/shapes`
 * because the reports answer it too. Only the paging experiment has a shape of its own.
 */

import type { Section } from "~/core/http/shapes";

/**
 * The pagination experiment answers a shape of its own, and it has to: what it is DEMONSTRATING is
 * the paging, so where you are in it is the payload rather than something wrapped around it.
 *
 * `page` is ZERO-BASED — `_page_param` defaults to 0 and `?page=1` is the SECOND page. That is
 * stated here rather than translated, because the number in the URL and the number in the OFFSET
 * the debug panel shows are the same number, and quietly adding one to it on the way in would make
 * this page lie about the one thing it exists to show.
 */
export interface LabPagination {
  section: Section;
  page: number;
  has_prev: boolean;
  has_next: boolean;
}
