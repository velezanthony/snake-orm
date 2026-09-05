/**
 * LIMIT/OFFSET over the volume table. Page through it and watch the OFFSET change in the panel.
 *
 * The page number lives in the URL — `?page=3` — and not in a `useState`. That is the difference
 * between a control and a page you can link to: a reader who found something on page seven can send
 * that page to somebody, and the back button steps through the pages instead of leaving the lab.
 *
 * It is ZERO-BASED, and left that way on purpose. The number in the URL is the number in the OFFSET
 * the panel shows underneath; adding one to it for the sake of looking friendlier would make this
 * page disagree with the SQL it exists to display.
 *
 * The prev/next state comes from the SERVER — `has_prev` and `has_next` — rather than from a total
 * this page would have to be told. That is the whole point of keyset-shaped paging over a table
 * "with potentially millions of rows": nobody counted them.
 */

import { useSearchParams } from "react-router";

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { SectionTable } from "@organisms/SectionTable";
import { Button } from "@atoms/Button";
import { Code } from "@atoms/Text";
import { useLabPagination } from "~/domains/lab/viewmodels";

export function LabPaginationPage() {
  const [params, setParams] = useSearchParams();
  const page = Math.max(0, Number(params.get("page") ?? 0) || 0);
  const result = useLabPagination(page);

  return (
    <>
      <PageHead
        title="Lab · Pagination"
        lede={
          <>
            LIMIT/OFFSET over the volume table (visits). Page through it and watch the{" "}
            <Code>OFFSET</Code> change in the panel below. The page number is zero-based, because it
            is the same number the OFFSET is computed from.
          </>
        }
      />

      <DataState resource={result} loading="Running the query…">
        {(data) => (
          <>
            <div className="pager mb-4">
              <Button
                size="sm"
                variant="ghost"
                disabled={!data.has_prev}
                onClick={() => setParams({ page: String(page - 1) })}
              >
                ← Previous
              </Button>
              <span className="pager-info">Page {data.page}</span>
              <Button
                size="sm"
                variant="ghost"
                disabled={!data.has_next}
                onClick={() => setParams({ page: String(page + 1) })}
              >
                Next →
              </Button>
            </div>

            <SectionTable section={data.section} />
          </>
        )}
      </DataState>
    </>
  );
}
