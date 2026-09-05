/** The confirmation, and it names the PAIR — because neither half of the key identifies a row. */

import { useNavigate, useParams } from "react-router";

import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { DataState } from "@organisms/DataState";
import { Button, ButtonLink } from "@atoms/Button";
import { ArticleCard, CardBody, CardFoot, CardHead } from "@molecules/Card";
import { useAction } from "~/core/hooks/useAction";
import { stockWrites, useStockRow } from "~/domains/inventory/viewmodels";

export function StockDeletePage() {
  const params = useParams();
  const warehouseId = Number(params.warehouseId);
  const skuId = Number(params.skuId);
  const navigate = useNavigate();

  const stock = useStockRow(warehouseId, skuId);

  const remove = useAction(async () => {
    await stockWrites.remove(warehouseId, skuId);
    await navigate(href("inventory.list"), { replace: true });
  });

  return (
    <DataState resource={stock} loading="Reading the pair…">
      {(row) => (
        <ArticleCard className="max-w-lg">
          <CardHead title={<span className="text-xl">Delete stock row</span>} />
          <CardBody className="text-ink-600">
            {remove.error !== null ? <Alert kind="error">{remove.error}</Alert> : null}
            Are you sure you want to delete the pair{" "}
            <strong className="text-ink-900">
              {row.warehouse ?? `#${warehouseId}`} · {row.sku ?? `#${skuId}`}
            </strong>
            ? Its movements stay; the row that ties them to a shelf does not.
          </CardBody>
          <CardFoot>
            <Button variant="danger" disabled={remove.pending} onClick={() => void remove.run()}>
              {remove.pending ? "Deleting…" : "Yes, delete it"}
            </Button>
            <ButtonLink to={href("inventory.detail", { warehouseId: warehouseId, skuId: skuId })}>Cancel</ButtonLink>
          </CardFoot>
        </ArticleCard>
      )}
    </DataState>
  );
}
