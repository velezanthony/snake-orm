/**
 * What this customer has ordered, and what was on each order.
 *
 * The lines below came back in ONE extra statement for the whole history, not one per order — which
 * is what reading the same thing from the order sheet costs, one click at a time.
 */

import { useParams } from "react-router";

import { href } from "~/config/href";

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { Badge } from "@atoms/Badge";
import { ButtonLink } from "@atoms/Button";
import { Card, CardHead } from "@molecules/Card";
import { fromDecimalString } from "~/core/lib/money";
import { useCustomerOrders } from "~/domains/orders/viewmodels";

export function CustomerSheetPage() {
  const customerId = Number(useParams().customerId);
  const orders = useCustomerOrders(customerId);

  return (
    <>
      <PageHead
        title={`Customer #${customerId}`}
        lede="What this customer has ordered, and what was on each order. None of the statements behind this page grows with how long the customer has been buying."
        actions={
          <ButtonLink size="sm" to={href("orders.report")}>
            ← The report
          </ButtonLink>
        }
      />

      <DataState resource={orders} loading="Reading the history…">
        {(rows) => (
          <Card>
            <CardHead title="Orders" sub="Every order this person has placed, newest first." />
            <DataTable
              bare
              label="Customer orders"
              caption="Every order of this customer, with its state and total."
              rows={rows}
              rowKey={(order) => order.id}
              empty="this customer has never ordered"
              columns={[
                {
                  header: "Reference",
                  cell: (order) => (
                    <a className="font-medium text-ink-900 hover:text-brand-700" href={href("orders.detail", { orderId: order.id })}>
                      {order.reference}
                    </a>
                  ),
                },
                { header: "Warehouse", cell: (order) => <span className="muted">{order.warehouse ?? `#${order.warehouse_id}`}</span> },
                { header: "State", cell: (order) => <Badge>{order.state}</Badge> },
                { header: "Total", cell: (order) => fromDecimalString(order.total) },
                { header: "Placed", cell: (order) => <span className="muted">{order.placed_at}</span> },
              ]}
            />
          </Card>
        )}
      </DataState>
    </>
  );
}
