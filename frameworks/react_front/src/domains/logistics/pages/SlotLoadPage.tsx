/**
 * A window whose span is a VALUE and not a count of rows.
 *
 * The band column is `RANGE BETWEEN n PRECEDING AND n FOLLOWING` over the booking hour, so two vans
 * booked into the SAME hour read the same figure — a tie is not a step. With `ROWS` each of them
 * would get a window of its own and three different numbers would come out of one hour.
 */

import { Badge } from "@atoms/Badge";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { useSlotLoad } from "~/domains/logistics/viewmodels";

export function SlotLoadPage() {
  const load = useSlotLoad();

  return (
    <>
      <PageHead
        title="Slot load"
        lede="A window whose span is a value and not a count of rows. The band column is RANGE BETWEEN n PRECEDING AND n FOLLOWING over the booking hour, so it holds everything within n hours of that slot — and two vans booked into the SAME hour read the same figure, because a tie is not a step."
      />

      <DataState resource={load} loading="Opening the window…">
        {(rows) => (
          <DataTable
            label="Slot load"
            caption="Units per booking slot, with the band the window totalled around it."
            rows={rows.map((row, index) => ({ ...row, index }))}
            // A depot can have several rows in the SAME hour — the very tie the RANGE window exists
            // to handle — so the position is the only identity these rows have.
            rowKey={(row) => `${row.depot}-${row.slot_hour}-${row.index}`}
            empty="nothing booked"
            columns={[
              { header: "Depot", cell: (row) => <span className="font-medium text-ink-900">{row.depot}</span> },
              { header: "Hour", cell: (row) => <span className="muted">{String(row.slot_hour).padStart(2, "0")}:00</span> },
              { header: "Units", cell: (row) => row.units },
              { header: "Band", cell: (row) => <span className="muted">{row.band_units}</span> },
              { header: "Peak", cell: (row) => (row.is_peak ? <Badge tone="ok">Peak</Badge> : <Badge>—</Badge>) },
            ]}
          />
        )}
      </DataState>
    </>
  );
}
