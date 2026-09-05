/**
 * One pair, and the to-many that hangs off a foreign key TWO COLUMNS WIDE, newest first.
 *
 * The two writes on this page are the domain's operations rather than a form: `receive` creates the
 * row if it was not there, and `ship` refuses with a 409 BEFORE writing when there are not that
 * many — the rule lives in the use case, not in a disabled button.
 */

import * as fields from "~/core/lib/form";
import { useParams } from "react-router";

import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { Button, ButtonLink } from "@atoms/Button";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { Field, Input } from "@atoms/Field";
import { DescriptionList } from "@molecules/DescriptionList";
import { useAction } from "~/core/hooks/useAction";
import { stockWrites, useStockPair } from "~/domains/inventory/viewmodels";

export function StockDetailPage() {
  const params = useParams();
  const warehouseId = Number(params.warehouseId);
  const skuId = Number(params.skuId);

  const pair = useStockPair(warehouseId, skuId);

  const move = useAction(async (direction: "receive" | "ship", units: number) => {
    if (direction === "receive") await stockWrites.receive(warehouseId, skuId, units);
    else await stockWrites.ship(warehouseId, skuId, units);
    pair.reload();
  });

  return (
    <DataState resource={pair} loading="Reading the pair…">
      {({ stock, movements }) => (
        <>
          <PageHead
            title={`${stock.warehouse ?? `#${warehouseId}`} · ${stock.sku ?? `#${skuId}`}`}
            lede="The to-many that hangs off a foreign key two columns wide, newest first."
            actions={
              <>
                <ButtonLink size="sm" to={href("inventory.update", { warehouseId: warehouseId, skuId: skuId })}>
                  Edit
                </ButtonLink>
                <ButtonLink size="sm" variant="danger" to={href("inventory.delete", { warehouseId: warehouseId, skuId: skuId })}>
                  Delete
                </ButtonLink>
              </>
            }
          />

          {move.error !== null ? <Alert kind="error">{move.error}</Alert> : null}

          <Card className="mb-6">
            <CardHead title="Levels" sub="Available is the engine's subtraction, not this page's." />
            <CardBody>
              <DescriptionList
                rows={[
                  ["On hand", stock.on_hand],
                  ["Reserved", stock.reserved],
                  ["Available", stock.available ?? "—"],
                  ["Last counted", stock.counted_at ?? "— never —"],
                ]}
              />
            </CardBody>
          </Card>

          <Card className="mb-6">
            <CardHead
              title="Move goods"
              sub="Receiving creates the row if it was not there. Shipping refuses BEFORE writing when there are not that many."
            />
            <CardBody>
              <form
                className="flex flex-wrap items-end gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const data = new FormData(event.currentTarget);
                  void move.run(
                    (data.get("direction") as "receive" | "ship") ?? "receive",
                    fields.number(data, "units"),
                  );
                }}
              >
                <Field id="units" label="Units">
                  <Input type="number" id="units" name="units" min={1} defaultValue={1} required />
                </Field>
                <Button type="submit" name="direction" value="receive" disabled={move.pending}>
                  Receive
                </Button>
                <Button
                  type="submit"
                  name="direction"
                  value="ship"
                  variant="ghost"
                  disabled={move.pending}
                >
                  Ship
                </Button>
              </form>
            </CardBody>
          </Card>

          <Card>
            <CardHead title="Movements" sub="The to-many over the composite key, newest first." />
            <DataTable
              bare
              label="Movements"
              caption="Every movement recorded against this pair."
              rows={movements}
              rowKey={(movement) => movement.id}
              empty="nothing has moved"
              columns={[
                { header: "#", cell: (m) => <span className="muted">{m.id}</span> },
                { header: "Quantity", cell: (m) => m.quantity },
                { header: "Reason", cell: (m) => <span className="muted">{m.reason}</span> },
                { header: "When", cell: (m) => <span className="muted">{m.happened_at}</span> },
              ]}
            />
          </Card>
        </>
      )}
    </DataState>
  );
}
