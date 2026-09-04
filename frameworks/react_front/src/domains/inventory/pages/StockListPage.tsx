/**
 * A page of stock rows with `include(Stock.warehouse, Stock.sku)`: one SELECT with two JOINs, plus
 * one COUNT for the pager. Thirty rows and three rows cost the same.
 */

import { href } from "~/config/href";

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { ButtonLink } from "@atoms/Button";
import { Pager } from "@molecules/Pager";
import { usePageParam } from "~/core/hooks/usePageParam";
import { Code } from "@atoms/Text";
import { useStockPage } from "~/domains/inventory/viewmodels";

export function StockListPage() {
  const [page, setPage] = usePageParam();
  const stock = useStockPage(page);

  return (
    <>
      <PageHead
        title="Stock"
        lede={
          <>
            A page of stock rows with <Code>include(Stock.warehouse, Stock.sku)</Code>: one SELECT
            with two JOINs, plus one COUNT for the pager. Thirty rows and three rows cost the same.
          </>
        }
        actions={
          <ButtonLink size="sm" to={href("inventory.create")}>
            New stock row
          </ButtonLink>
        }
      />

      <DataState resource={stock} loading="Reading the stockroom…">
        {(payload) => (
          <>
            <DataTable
              label="Stock"
              caption="Every stock row, keyed on the pair (warehouse, SKU)."
              rows={payload.rows}
              // The KEY is the PAIR, because neither half identifies a row on its own. The domain's
              // whole shape, showing up even here.
              rowKey={(row) => `${row.warehouse_id}-${row.sku_id}`}
              empty="nothing in stock"
              columns={[
                { header: "Warehouse", cell: (row) => <span className="font-medium text-ink-900">{row.warehouse ?? `#${row.warehouse_id}`}</span> },
                {
                  header: "SKU",
                  cell: (row) => (
                    <a className="font-medium text-ink-900 hover:text-brand-700" href={href("inventory.detail", { warehouseId: row.warehouse_id, skuId: row.sku_id })}>
                      {row.sku ?? `#${row.sku_id}`}
                    </a>
                  ),
                },
                { header: "On hand", cell: (row) => row.on_hand },
                { header: "Reserved", cell: (row) => <span className="muted">{row.reserved}</span> },
                // Read, never computed here: the engine already subtracted, and doing it again on
                // the client would be a second definition of "available".
                { header: "Available", cell: (row) => row.available ?? "—" },
                {
                  header: "Actions",
                  align: "right",
                  cell: (row) => (
                    <ButtonLink size="sm" to={href("inventory.update", { warehouseId: row.warehouse_id, skuId: row.sku_id })}>
                      Edit
                    </ButtonLink>
                  ),
                },
              ]}
            />

            <Pager page={payload.page} pages={payload.pages} total={payload.total} onPage={setPage} />
          </>
        )}
      </DataState>
    </>
  );
}
