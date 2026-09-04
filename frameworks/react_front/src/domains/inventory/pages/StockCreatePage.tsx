/**
 * A physical count is an UPSERT: it says the pair holds this many, whether or not the row was
 * already there.
 *
 * Which is why this page and the edit page are not the same form with a flag. Counting states a
 * fact about a shelf; correcting states that the record was wrong. The API tells them apart by the
 * verb — `PUT` here, `PATCH` there — and so does this demo.
 */

import * as fields from "~/core/lib/form";
import { useNavigate } from "react-router";

import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { Button, ButtonLink } from "@atoms/Button";
import { Card, CardForm } from "@molecules/Card";
import { Field, Input, Select } from "@atoms/Field";
import { FormActions } from "@molecules/FormActions";
import { useAction } from "~/core/hooks/useAction";
import { stockWrites, useStockCatalogue } from "~/domains/inventory/viewmodels";

export function StockCreatePage() {
  const navigate = useNavigate();

  const catalogue = useStockCatalogue();

  const count = useAction(async (form: HTMLFormElement) => {
    const data = new FormData(form);
    const warehouseId = fields.number(data, "warehouse_id");
    const skuId = fields.number(data, "sku_id");
    await stockWrites.count(warehouseId, skuId, { on_hand: fields.number(data, "on_hand") });
    await navigate(href("inventory.detail", { warehouseId: warehouseId, skuId: skuId }));
  });

  return (
    <>
      <PageHead
        title="New stock row"
        lede="A physical count is an upsert: it says the pair holds this many, whether or not the row was already there."
      />

      {count.error !== null ? <Alert kind="error">{count.error}</Alert> : null}

      <DataState resource={catalogue} loading="Reading the catalogue…">
        {({ warehouses, skus }) => (
          <Card className="max-w-md">
            <CardForm onSubmit={(form) => void count.run(form)}>
              <Field id="warehouse_id" label="Warehouse">
                <Select id="warehouse_id" name="warehouse_id" defaultValue={warehouses[0]?.id}>
                  {warehouses.map((warehouse) => (
                    <option key={warehouse.id} value={warehouse.id}>
                      {warehouse.code} · {warehouse.name}
                    </option>
                  ))}
                </Select>
              </Field>

              <Field id="sku_id" label="SKU">
                <Select id="sku_id" name="sku_id" defaultValue={skus[0]?.id}>
                  {skus.map((sku) => (
                    <option key={sku.id} value={sku.id}>
                      {sku.name}
                    </option>
                  ))}
                </Select>
              </Field>

              <Field id="on_hand" label="Counted on hand">
                <Input type="number" id="on_hand" name="on_hand" min={0} defaultValue={0} required />
              </Field>

              <FormActions>
                <Button type="submit" disabled={count.pending}>
                  {count.pending ? "Counting…" : "Record the count"}
                </Button>
                <ButtonLink to={href("inventory.list")}>Cancel</ButtonLink>
              </FormActions>
            </CardForm>
          </Card>
        )}
      </DataState>
    </>
  );
}
