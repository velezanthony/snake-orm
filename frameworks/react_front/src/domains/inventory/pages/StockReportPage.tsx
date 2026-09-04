/**
 * Five questions a plain `filter()` cannot answer, in five statements that do not grow with the
 * data.
 *
 * Each table says which part of the ORM produced it, because a number with no provenance teaches
 * nothing.
 */

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { StateBadge } from "@atoms/Badge";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { DescriptionList } from "@molecules/DescriptionList";
import { useStockReport } from "~/domains/inventory/viewmodels";

export function StockReportPage() {
  const report = useStockReport();

  return (
    <>
      <PageHead
        title="Stock report"
        lede="Five questions a plain filter() cannot answer, in five statements that do not grow with the data. Each table below says which part of the ORM produced it, because a number with no provenance teaches nothing."
      />

      <DataState resource={report} loading="Adding it up…">
        {(data) => (
          <>
            <Card className="mb-6">
              <CardHead title="Warehouses" sub="annotate: an aggregate per row, computed beside the row it belongs to." />
              <DataTable
                bare
                label="Warehouse totals"
                caption="Every warehouse with how many SKUs it stocks and how many units that is."
                rows={data.warehouses}
                rowKey={(row) => row.warehouse.id}
                empty="no warehouses"
                columns={[
                  { header: "Warehouse", cell: ({ warehouse }) => <span className="font-medium text-ink-900">{warehouse.code} · {warehouse.name}</span> },
                  { header: "State", cell: ({ warehouse }) => <StateBadge on={warehouse.active} yes="Open" no="Closed" /> },
                  { header: "SKUs", cell: (row) => <span className="muted">{row.sku_count}</span> },
                  { header: "Units", cell: (row) => row.total_units },
                ]}
              />
            </Card>

            <Card className="mb-6">
              <CardHead title="Busiest SKUs" sub="GROUP BY + HAVING: only the ones that moved enough to matter." />
              <DataTable
                bare
                label="Busiest SKUs"
                caption="The SKUs with the most movements, and what they netted."
                rows={data.busy_skus}
                rowKey={(sku) => sku.sku_name}
                empty="nothing has moved"
                columns={[
                  { header: "SKU", cell: (s) => <span className="font-medium text-ink-900">{s.sku_name}</span> },
                  { header: "Moves", cell: (s) => <span className="muted">{s.moves}</span> },
                  { header: "Net", cell: (s) => s.net_delta },
                ]}
              />
            </Card>

            <Card className="mb-6">
              <CardHead title="Ranking" sub="A window function: the position of each line WITHIN its warehouse." />
              <DataTable
                bare
                label="Stock ranking"
                caption="The best-stocked lines, ranked inside each warehouse."
                rows={data.ranking}
                rowKey={(row) => `${row.warehouse_code}-${row.sku_name}`}
                empty="nothing in stock"
                columns={[
                  { header: "#", cell: (r) => <span className="muted">{r.position}</span> },
                  { header: "Warehouse", cell: (r) => r.warehouse_code },
                  { header: "SKU", cell: (r) => <span className="font-medium text-ink-900">{r.sku_name}</span> },
                  { header: "On hand", cell: (r) => r.on_hand },
                ]}
              />
            </Card>

            <Card className="mb-6">
              <CardHead title="Coverage" sub="A join + distinct: how many of the catalogue's SKUs have ever moved." />
              <CardBody>
                <DescriptionList
                  rows={[
                    ["SKUs that have moved", data.moved_skus.length],
                    ["SKUs in the catalogue", data.total_skus],
                  ]}
                />
              </CardBody>
            </Card>

            <Card>
              <CardHead title="Trail" sub="A running total and a moving average, both window functions over the movements." />
              <DataTable
                bare
                label="Movement trail"
                caption="Movements with the running total and moving average the engine computed alongside."
                rows={data.trail.map((row, index) => ({ ...row, index }))}
                rowKey={(row) => `${row.sku_name}-${row.index}`}
                empty="nothing has moved"
                columns={[
                  { header: "SKU", cell: (r) => <span className="font-medium text-ink-900">{r.sku_name}</span> },
                  { header: "Delta", cell: (r) => r.delta },
                  { header: "Running", cell: (r) => <span className="muted">{r.running}</span> },
                  { header: "Moving avg", cell: (r) => <span className="muted">{r.moving}</span> },
                ]}
              />
            </Card>
          </>
        )}
      </DataState>
    </>
  );
}
