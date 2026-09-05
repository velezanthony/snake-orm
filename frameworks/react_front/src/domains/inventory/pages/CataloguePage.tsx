/**
 * What the inventory is made OF, as against what is IN it.
 *
 * A stock pair points at a warehouse and a SKU, and until this page existed neither could be made
 * from one — the demo could only stock what the seeder had built. The warehouse-wide `reserve`
 * lands here for the same reason: it reserves across a WAREHOUSE's whole stock in one statement, so
 * it belongs on the screen where a warehouse is a row rather than on one about a single pair.
 */


import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { StateBadge } from "@atoms/Badge";
import { Button, ButtonLink } from "@atoms/Button";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { useAction } from "~/core/hooks/useAction";
import { stockWrites, useCatalogue } from "~/domains/inventory/viewmodels";

export function CataloguePage() {
  const catalogue = useCatalogue();

  const reserve = useAction(async (warehouseId: number, units: number) => {
    await stockWrites.reserve(warehouseId, units);
    catalogue.reload();
  });

  return (
    <>
      <PageHead
        title="Warehouses & SKUs"
        lede="What the inventory is made OF, as against what is IN it. Two statements, and neither grows with the rows: how much each warehouse holds is an aggregate per row, which is the report's question and the report answers it in one."
      />

      {reserve.error !== null ? <Alert kind="error">{reserve.error}</Alert> : null}

      <DataState resource={catalogue} loading="Reading the catalogue…">
        {({ stats, skus }) => (
          <>
            <Card className="mb-6">
              <CardHead
                title="Warehouses"
                sub="The reserve here takes units across the warehouse's WHOLE stock, in one statement."
              />
              <DataTable
                bare
                label="Warehouses"
                caption="Every warehouse with how many SKUs it stocks and how many units that is."
                rows={stats}
                rowKey={(row) => row.warehouse.id}
                empty="no warehouses"
                columns={[
                  {
                    header: "Code",
                    cell: ({ warehouse }) => (
                      <a className="font-medium text-ink-900 hover:text-brand-700" href={href("inventory.warehouse", { warehouseId: warehouse.id })}>
                        {warehouse.code}
                      </a>
                    ),
                  },
                  { header: "Name", cell: ({ warehouse }) => warehouse.name },
                  { header: "State", cell: ({ warehouse }) => <StateBadge on={warehouse.active} yes="Open" no="Closed" /> },
                  { header: "SKUs", cell: (row) => <span className="muted">{row.sku_count}</span> },
                  { header: "Units", cell: (row) => <span className="muted">{row.total_units}</span> },
                  {
                    header: "Actions",
                    align: "right",
                    cell: ({ warehouse }) => (
                      <div className="inline-flex gap-2">
                        <ButtonLink size="sm" to={href("inventory.warehouse", { warehouseId: warehouse.id })}>
                          Sheet
                        </ButtonLink>
                        <Button size="sm" variant="ghost" disabled={reserve.pending} onClick={() => void reserve.run(warehouse.id, 1)}>
                          Reserve 1 each
                        </Button>
                      </div>
                    ),
                  },
                ]}
              />
            </Card>

            <Card>
              <CardHead title="SKUs" sub="What a stock row can point at. The column types are the demo's whole type tour." />
              <CardBody className="p-0">
                <DataTable
                  bare
                  label="SKUs"
                  caption="Every SKU with its kind, price and physical facts."
                  rows={skus}
                  rowKey={(sku) => sku.id}
                  empty="no SKUs"
                  columns={[
                    { header: "Name", cell: (sku) => <span className="font-medium text-ink-900">{sku.name}</span> },
                    { header: "Kind", cell: (sku) => <span className="muted">{sku.kind}</span> },
                    { header: "Price", cell: (sku) => sku.price },
                    { header: "Weight", cell: (sku) => <span className="muted">{sku.weight_kg} kg</span> },
                  ]}
                />
              </CardBody>
            </Card>
          </>
        )}
      </DataState>
    </>
  );
}
