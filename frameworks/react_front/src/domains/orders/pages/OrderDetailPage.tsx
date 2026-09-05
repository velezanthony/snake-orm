/**
 * One order and its lines: the to-many over the SECOND composite key of the demo — order and SKU
 * together.
 */

import { useParams } from "react-router";

import { href } from "~/config/href";

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { Badge } from "@atoms/Badge";
import { ButtonLink } from "@atoms/Button";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { DescriptionList } from "@molecules/DescriptionList";
import { fromCents, fromDecimalString } from "~/core/lib/money";
import { useOrderSheet } from "~/domains/orders/viewmodels";

export function OrderDetailPage() {
  const orderId = Number(useParams().orderId);

  const sheet = useOrderSheet(orderId);

  return (
    <DataState resource={sheet} loading="Reading the order…">
      {({ order, lines }) => (
        <>
          <PageHead
            title={order.reference}
            lede="The to-many over the second composite key of the demo: order and SKU together."
            actions={
              <>
                <ButtonLink size="sm" to={href("orders.operateOne", { orderId: order.id })}>
                  Operate
                </ButtonLink>
                <ButtonLink size="sm" to={href("orders.list")}>
                  ← Every order
                </ButtonLink>
              </>
            }
          />

          <Card className="mb-6">
            <CardHead title="The order" aside={<Badge tone="muted">{order.state}</Badge>} />
            <CardBody>
              <DescriptionList
                rows={[
                  ["Customer", order.customer ?? `#${order.customer_id}`],
                  ["Warehouse", order.warehouse ?? `#${order.warehouse_id}`],
                  ["Placed", order.placed_at],
                  ["Total", fromDecimalString(order.total)],
                  [
                    "Invoice",
                    order.invoice_id === null
                      ? "— none attached —"
                      : `#${order.invoice_id}${
                          order.invoice_amount_cents === null || order.invoice_amount_cents === undefined
                            ? ""
                            : ` · ${fromCents(order.invoice_amount_cents)}`
                        }`,
                  ],
                ]}
              />
            </CardBody>
          </Card>

          <Card>
            <CardHead title="Lines" sub="One statement for the whole to-many, keyed on the pair (order, SKU)." />
            <DataTable
              bare
              label="Order lines"
              caption="Every line of this order, with the price it was placed at."
              rows={lines}
              rowKey={(line) => `${line.order_id}-${line.sku_id}`}
              empty="this order has no lines"
              columns={[
                { header: "SKU", cell: (line) => <span className="font-medium text-ink-900">{line.sku ?? `#${line.sku_id}`}</span> },
                { header: "Quantity", cell: (line) => line.quantity },
                { header: "Unit price", cell: (line) => fromDecimalString(line.unit_price) },
              ]}
            />
          </Card>
        </>
      )}
    </DataState>
  );
}
