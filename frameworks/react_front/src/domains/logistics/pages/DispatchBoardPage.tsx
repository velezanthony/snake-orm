/**
 * Backwards scheduling, in one statement.
 *
 * The customer fixes the END of the chain and the depot works out when the van has to be on the
 * road, so the deadline is the promise shifted BACKWARD by the lead time — the direction billing
 * never needed, because a due date only ever moves forward.
 */

import { href } from "~/config/href";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { useDispatchBoard } from "~/domains/logistics/viewmodels";

export function DispatchBoardPage() {
  const board = useDispatchBoard();

  return (
    <>
      <PageHead
        title="Dispatch board"
        lede="Backwards scheduling, in one statement. The customer fixes the END of the chain and the depot works out when the van has to be on the road, so the deadline is the promise shifted backward by the lead time — the direction billing never needed, because a due date only ever moves forward."
      />

      <DataState resource={board} loading="Reading the board…">
        {(rows) => (
          <DataTable
            label="Dispatch board"
            caption="What has to leave, and the date the van must be on the road."
            rows={rows}
            rowKey={(row) => row.delivery_id}
            empty="nothing due"
            columns={[
              {
                header: "Reference",
                cell: (row) => (
                  <a className="font-medium text-ink-900 hover:text-brand-700" href={href("logistics.detail", { deliveryId: row.delivery_id })}>
                    {row.reference}
                  </a>
                ),
              },
              { header: "Promised", cell: (row) => <span className="muted">{row.promised_on}</span> },
              { header: "Leave by", cell: (row) => <span className="muted">{row.leave_by}</span> },
            ]}
          />
        )}
      </DataState>
    </>
  );
}
