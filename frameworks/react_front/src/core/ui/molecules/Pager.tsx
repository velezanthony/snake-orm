/**
 * The pager the paginated listings share, and the one place the page number leaves the URL.
 *
 * It stays in `?page=` rather than in a `useState`, which is what separates a control from a page
 * you can send somebody: the back button steps through the pages instead of leaving the section,
 * and a reload lands where it left off.
 */

import { Button } from "@atoms/Button";

export function Pager({
  page,
  pages,
  total,
  onPage,
}: {
  page: number;
  pages: number;
  total: number;
  onPage: (page: number) => void;
}) {
  return (
    <div className="pager">
      <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ← Previous
      </Button>
      <span className="pager-info">
        Page {page} of {pages} · {total} rows
      </span>
      <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next →
      </Button>
    </div>
  );
}
