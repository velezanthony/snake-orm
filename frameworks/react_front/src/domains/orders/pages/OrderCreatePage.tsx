/**
 * Placing an order prices every line off its SKU, writes the order and its lines, and commits ONCE.
 *
 * The reference is unique, and it is checked LAST on purpose: it is the only one of the four
 * refusals another request can turn true while this form is being filled in.
 *
 * The lines are the one piece of local state on the page, and they have to be: a line is added
 * before anything is sent, so there is nothing on the server to read them back from yet.
 */

import * as fields from "~/core/lib/form";
import { useState } from "react";
import { useNavigate } from "react-router";

import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { Button, ButtonLink } from "@atoms/Button";
import { Card, CardBody, CardForm, CardHead } from "@molecules/Card";
import { Field, Input, Select } from "@atoms/Field";
import { FormActions } from "@molecules/FormActions";
import { useAction } from "~/core/hooks/useAction";
import { orderWrites, useOrderCatalogue } from "~/domains/orders/viewmodels";

interface DraftLine {
  sku_id: number;
  quantity: number;
}

export function OrderCreatePage() {
  const navigate = useNavigate();
  const [lines, setLines] = useState<DraftLine[]>([]);

  const catalogue = useOrderCatalogue();

  const place = useAction(async (form: HTMLFormElement) => {
    const data = new FormData(form);
    const order = await orderWrites.place({
      reference: fields.text(data, "reference"),
      customer_id: fields.number(data, "customer_id"),
      warehouse_id: fields.number(data, "warehouse_id"),
      lines,
    });
    await navigate(href("orders.detail", { orderId: order.id }));
  });

  return (
    <>
      <PageHead
        title="New order"
        lede="Placing an order prices every line off its SKU, writes the order and its lines, and commits ONCE. The reference is unique, and it is checked last on purpose: it is the only one of the four refusals another request can turn true while this form is being filled in."
      />

      {place.error !== null ? <Alert kind="error">{place.error}</Alert> : null}

      <DataState resource={catalogue} loading="Reading the catalogue…">
        {({ warehouses, skus }) => (
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHead title="The order" sub="Three fields, and the lines beside them." />
              <CardForm onSubmit={(form) => void place.run(form)}>
                <Field id="reference" label="Reference">
                  <Input type="text" id="reference" name="reference" placeholder="ORD-000999" autoFocus required />
                </Field>

                <Field id="customer_id" label="Customer id">
                  <Input type="number" id="customer_id" name="customer_id" min={1} defaultValue={1} required />
                </Field>

                <Field id="warehouse_id" label="Warehouse">
                  <Select id="warehouse_id" name="warehouse_id" defaultValue={warehouses[0]?.id}>
                    {warehouses.map((warehouse) => (
                      <option key={warehouse.id} value={warehouse.id}>
                        {warehouse.code} · {warehouse.name}
                      </option>
                    ))}
                  </Select>
                </Field>

                <FormActions>
                  <Button type="submit" disabled={place.pending || lines.length === 0}>
                    {place.pending ? "Placing…" : "Place the order"}
                  </Button>
                  <ButtonLink to={href("orders.list")}>Cancel</ButtonLink>
                </FormActions>
              </CardForm>
            </Card>

            <Card>
              <CardHead title="Lines" sub="The API prices each one off its SKU. Nothing here sends a price." />
              <CardBody>
                <form
                  className="flex flex-wrap items-end gap-2 pb-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const data = new FormData(event.currentTarget);
                    const sku_id = fields.number(data, "sku_id");
                    const quantity = fields.number(data, "quantity");
                    // Setting rather than appending, for the same reason the API's line endpoint is
                    // a PUT: a SKU named twice is one line with the later quantity, not two lines.
                    setLines((current) => [...current.filter((l) => l.sku_id !== sku_id), { sku_id, quantity }]);
                    event.currentTarget.reset();
                  }}
                >
                  <Field id="sku_id" label="SKU">
                    <Select id="sku_id" name="sku_id" defaultValue={skus[0]?.id}>
                      {skus.map((sku) => (
                        <option key={sku.id} value={sku.id}>
                          {sku.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field id="quantity" label="Units">
                    <Input type="number" id="quantity" name="quantity" min={1} defaultValue={1} required />
                  </Field>
                  <Button variant="ghost" type="submit">
                    Add line
                  </Button>
                </form>

                <DataTable
                  label="Draft lines"
                  caption="The lines this order will be placed with."
                  rows={lines}
                  rowKey={(line) => line.sku_id}
                  empty="add at least one line"
                  columns={[
                    {
                      header: "SKU",
                      cell: (line) => (
                        <span className="font-medium text-ink-900">
                          {skus.find((sku) => sku.id === line.sku_id)?.name ?? `#${line.sku_id}`}
                        </span>
                      ),
                    },
                    { header: "Units", cell: (line) => line.quantity },
                    {
                      header: "Actions",
                      align: "right",
                      cell: (line) => (
                        <Button size="sm" variant="danger" onClick={() => setLines((current) => current.filter((l) => l.sku_id !== line.sku_id))}>
                          Remove
                        </Button>
                      ),
                    },
                  ]}
                />
              </CardBody>
            </Card>
          </div>
        )}
      </DataState>
    </>
  );
}
