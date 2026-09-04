/**
 * What a replenishment meeting opens with.
 *
 * The rows come off `LowStock`, a read-only VIEW the ORM queries like any other model and refuses to
 * write to — so the definition of "running out" (available below the line, not quantity below it)
 * lives in the database and not in this page.
 */

import { href } from "~/config/href";

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { useStockAlerts } from "~/domains/inventory/viewmodels";

export function StockAlertsPage() {
  const alerts = useStockAlerts();

  return (
    <>
      <PageHead
        title="Running out"
        lede="What a replenishment meeting opens with. The rows come off LowStock, a read-only view the ORM queries like any other model and refuses to write to, so the definition of “running out” — available below the line, not quantity below it — lives in the database and not in this page."
      />

      <DataState resource={alerts} loading="Asking the view…">
        {({ rows, warehouseName, skuName }) => (
          <DataTable
            label="Running out"
            caption="Every pair the view considers low, with what is on the shelf and what is held."
            rows={rows}
            rowKey={(row) => `${row.warehouse_id}-${row.sku_id}`}
            empty="nothing is running out"
            columns={[
              { header: "Warehouse", cell: (row) => <span className="font-medium text-ink-900">{warehouseName.get(row.warehouse_id) ?? `#${row.warehouse_id}`}</span> },
              {
                header: "SKU",
                cell: (row) => (
                  <a className="font-medium text-ink-900 hover:text-brand-700" href={href("inventory.detail", { warehouseId: row.warehouse_id, skuId: row.sku_id })}>
                    {skuName.get(row.sku_id) ?? `#${row.sku_id}`}
                  </a>
                ),
              },
              { header: "On hand", cell: (row) => row.on_hand },
              { header: "Reserved", cell: (row) => <span className="muted">{row.reserved}</span> },
            ]}
          />
        )}
      </DataState>
    </>
  );
}
