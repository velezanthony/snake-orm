/**
 * ONE warehouse, and what every line in it has been doing.
 *
 * The movements below did not arrive one query per line: they came back in a single select-in over
 * a foreign key TWO COLUMNS WIDE, which is the hardest relationship in these demos — a stock row is
 * identified by the pair (warehouse, SKU), so every parent binds two placeholders instead of one.
 */

import { useParams } from "react-router";

import { href } from "~/config/href";

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { ButtonLink } from "@atoms/Button";
import { Card, CardHead } from "@molecules/Card";
import { useWarehouseSheet } from "~/domains/inventory/viewmodels";

export function WarehouseSheetPage() {
  const warehouseId = Number(useParams().warehouseId);

  const sheet = useWarehouseSheet(warehouseId);

  return (
    <DataState resource={sheet} loading="Reading the warehouse…">
      {({ warehouse, lines }) => (
        <>
          <PageHead
            title={`${warehouse.code} · ${warehouse.name}`}
            lede="What is in this warehouse and what every line in it has been doing, on one page. The movements below came back in a single select-in over a foreign key two columns wide — so every parent binds two placeholders instead of one."
            actions={
              <ButtonLink size="sm" to={href("inventory.catalogue")}>
                ← The catalogue
              </ButtonLink>
            }
          />

          <Card>
            <CardHead
              title="Stock, with its movements"
              sub="One statement for the lines and one for every movement of every line."
            />
            <DataTable
              bare
              label="Warehouse stock"
              caption="Every line in this warehouse, with how much has moved through it."
              rows={lines}
              rowKey={(line) => `${line.warehouse_id}-${line.sku_id}`}
              empty="this warehouse is empty"
              columns={[
                {
                  header: "SKU",
                  cell: (line) => (
                    <a className="font-medium text-ink-900 hover:text-brand-700" href={href("inventory.detail", { warehouseId: line.warehouse_id, skuId: line.sku_id })}>
                      {line.sku ?? `#${line.sku_id}`}
                    </a>
                  ),
                },
                { header: "On hand", cell: (line) => line.on_hand },
                { header: "Reserved", cell: (line) => <span className="muted">{line.reserved}</span> },
                { header: "Movements", cell: (line) => <span className="muted">{line.movements.length}</span> },
                { header: "Latest", cell: (line) => <span className="muted">{line.movements[0]?.happened_at ?? "—"}</span> },
              ]}
            />
          </Card>
        </>
      )}
    </DataState>
  );
}
