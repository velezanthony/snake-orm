/**
 * The depots, with what each has moved. ONE statement for the whole screen.
 */

import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { useDepots } from "~/domains/logistics/viewmodels";

export function DepotListPage() {
  const depots = useDepots();

  return (
    <>
      <PageHead
        title="Depots"
        lede="One statement for the whole screen, whatever the number of depots. Both figures on a row are CORRELATED aggregates the engine computes beside the depot they belong to; walking depot.deliveries here instead would be this same page at one query per row — an N+1 inside the renderer, where no test counts."
      />

      <DataState resource={depots} loading="Reading the depots…">
        {(rows) => (
          <DataTable
            label="Depots"
            caption="Every depot, with the deliveries it has taken and the units they carried."
            rows={rows}
            rowKey={(depot) => depot.code}
            empty="no depots"
            columns={[
              { header: "Code", cell: (d) => <span className="font-medium text-ink-900">{d.code}</span> },
              { header: "Name", cell: (d) => d.name },
              { header: "Deliveries", cell: (d) => <span className="muted">{d.deliveries}</span> },
              { header: "Units", cell: (d) => <span className="muted">{d.units}</span> },
            ]}
          />
        )}
      </DataState>
    </>
  );
}
