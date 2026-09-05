/**
 * The page that makes TWO classic mistakes on purpose so the panel can catch them.
 *
 * It has no table, and that is the design. The endpoint answers `{ ran: true }` because its whole
 * output is the query log: an N+1 walked one row at a time, and the same SELECT issued twice.
 * Drawing rows here would give a reader something to look at other than the thing they came for.
 */

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { Empty } from "@atoms/Text";
import { useLabProblems } from "~/domains/lab/viewmodels";

export function LabProblemsPage() {
  const ran = useLabProblems();

  return (
    <>
      <PageHead
        title="Lab · Deliberate problems"
        lede="This page makes TWO classic mistakes so the panel can catch them. Open the panel below and look at the duplicates metric."
      />
      <DataState resource={ran} loading="Making the mistakes…">
        {() => (
          <Empty>
            The queries ran. Everything worth seeing is in the panel underneath — that is the point of
            this page.
          </Empty>
        )}
      </DataState>
    </>
  );
}
