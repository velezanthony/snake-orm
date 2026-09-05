/**
 * Correcting the levels of a row that already exists. The pair itself does not move.
 *
 * `PATCH` and not `PUT`: this is not a count. A count states what is on the shelf and creates the
 * row if there was none; a correction says the RECORD was wrong about a pair that exists.
 */

import * as fields from "~/core/lib/form";
import { useNavigate, useParams } from "react-router";

import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { Button, ButtonLink } from "@atoms/Button";
import { Card, CardForm } from "@molecules/Card";
import { Field, Input } from "@atoms/Field";
import { FormActions } from "@molecules/FormActions";
import { useAction } from "~/core/hooks/useAction";
import { stockWrites, useStockRow } from "~/domains/inventory/viewmodels";

export function StockEditPage() {
  const params = useParams();
  const warehouseId = Number(params.warehouseId);
  const skuId = Number(params.skuId);
  const navigate = useNavigate();

  const stock = useStockRow(warehouseId, skuId);

  const correct = useAction(async (form: HTMLFormElement) => {
    const data = new FormData(form);
    await stockWrites.correct(warehouseId, skuId, {
      on_hand: fields.number(data, "on_hand"),
      reserved: fields.number(data, "reserved"),
    });
    await navigate(href("inventory.detail", { warehouseId: warehouseId, skuId: skuId }));
  });

  return (
    <DataState resource={stock} loading="Reading the pair…">
      {(row) => (
        <>
          <PageHead
            title={`Edit ${row.warehouse ?? `#${warehouseId}`} · ${row.sku ?? `#${skuId}`}`}
            lede="Correcting the levels of a row that already exists. The pair itself does not move."
          />

          {correct.error !== null ? <Alert kind="error">{correct.error}</Alert> : null}

          <Card className="max-w-md">
            <CardForm onSubmit={(form) => void correct.run(form)}>
              <Field id="on_hand" label="On hand">
                <Input type="number" id="on_hand" name="on_hand" min={0} defaultValue={row.on_hand} required />
              </Field>

              <Field id="reserved" label="Reserved">
                <Input type="number" id="reserved" name="reserved" min={0} defaultValue={row.reserved} required />
              </Field>

              <FormActions>
                <Button type="submit" disabled={correct.pending}>
                  {correct.pending ? "Saving…" : "Save"}
                </Button>
                <ButtonLink to={href("inventory.detail", { warehouseId: warehouseId, skuId: skuId })}>Cancel</ButtonLink>
              </FormActions>
            </CardForm>
          </Card>
        </>
      )}
    </DataState>
  );
}
