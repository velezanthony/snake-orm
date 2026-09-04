/**
 * ONE LINE PER SUBMIT, because saving a line and removing one are two use cases and each commits.
 *
 * A single button covering both would be several transactions wearing one label, and a failure
 * halfway would leave the page showing an order that is neither what it was nor what was asked for.
 *
 * There is no form for the order's own fields, and that is the API rather than an omission: the
 * orders resource answers GET and DELETE and no PATCH. What an order IS gets fixed when it is
 * placed; what it CONTAINS is this page.
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
import { Field, Input, Select } from "@atoms/Field";
import { useAction } from "~/core/hooks/useAction";
import { fromDecimalString } from "~/core/lib/money";
import { orderWrites, useOrderCatalogue, useOrderSheet } from "~/domains/orders/viewmodels";

export function OrderEditPage() {
  const orderId = Number(useParams().orderId);

  const sheet = useOrderSheet(orderId);
  // The SKU list fills the picker and nothing else, so the page does not wait on it: the order's own
  // lines are what this screen is ABOUT, and holding them back until a catalogue arrives would make
  // the slower of two reads decide when anything appears.
  const catalogue = useOrderCatalogue();
  const skus = catalogue.data?.skus ?? [];

  const setLine = useAction(async (form: HTMLFormElement) => {
    const data = new FormData(form);
    await orderWrites.setLine(orderId, {
      sku_id: fields.number(data, "sku_id"),
      quantity: fields.number(data, "quantity"),
    });
    sheet.reload();
  });

  const removeLine = useAction(async (skuId: number) => {
    await orderWrites.removeLine(orderId, skuId);
    sheet.reload();
  });

  return (
    <DataState resource={sheet} loading="Reading the order…">
      {({ order, lines }) => (
        <>
          <PageHead
            title={`Edit ${order.reference}`}
            lede="One line per submit, because saving a line and removing one are two use cases and each commits. A single button covering both would be several transactions wearing one label, and a failure halfway would leave the page showing an order that is neither what it was nor what was asked for."
            actions={
              <ButtonLink size="sm" to={href("orders.detail", { orderId: order.id })}>
                ← The order
              </ButtonLink>
            }
          />

          {setLine.error !== null ? <Alert kind="error">{setLine.error}</Alert> : null}
          {removeLine.error !== null ? <Alert kind="error">{removeLine.error}</Alert> : null}

          <Card>
            <CardHead
              title="Lines"
              sub="Setting a quantity is a PUT — an upsert, so a retried request cannot double what the customer asked for."
            />
            <CardBody>
              <form
                className="flex flex-wrap items-end gap-2 pb-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void setLine.run(event.currentTarget);
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
                  <Input type="number" id="quantity" name="quantity" min={0} defaultValue={1} required />
                </Field>
                <Button type="submit" disabled={setLine.pending}>
                  Set the line
                </Button>
              </form>

              <DataTable
                label="Order lines"
                caption="The lines currently on this order."
                rows={lines}
                rowKey={(line) => `${line.order_id}-${line.sku_id}`}
                empty="this order has no lines"
                columns={[
                  { header: "SKU", cell: (line) => <span className="font-medium text-ink-900">{line.sku ?? `#${line.sku_id}`}</span> },
                  { header: "Units", cell: (line) => line.quantity },
                  { header: "Unit price", cell: (line) => fromDecimalString(line.unit_price) },
                  {
                    header: "Actions",
                    align: "right",
                    cell: (line) => (
                      <Button size="sm" variant="danger" disabled={removeLine.pending} onClick={() => void removeLine.run(line.sku_id)}>
                        Remove
                      </Button>
                    ),
                  },
                ]}
              />
            </CardBody>
          </Card>
        </>
      )}
    </DataState>
  );
}
