/**
 * The chooser: the DRAFTS, because a draft is the state all three operations are reachable from.
 *
 * The catalogue marks this page `in_sidebar` precisely because it is the one operation entry a link
 * can reach without a key — so the bare path is a list and the path with an id is the operation.
 */

import { href } from "~/config/href";
import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { Badge } from "@atoms/Badge";
import { ButtonLink } from "@atoms/Button";
import { fromDecimalString } from "~/core/lib/money";
import { useOpenOrders } from "~/domains/orders/viewmodels";

export function OrderOperateIndexPage() {
  const orders = useOpenOrders();

  return (
    <>
      <PageHead
        title="Operate an order"
        lede="The open orders, because those are the states the three operations are reachable from. Pick one and the next page reserves it under a row lock, settles it through a savepoint, or cancels it."
      />

      <DataState resource={orders} loading="Reading the orders…">
        {(open) => (
            <DataTable
              label="Open orders"
              caption="The orders an operation can still be performed on."
              rows={open}
              rowKey={(order) => order.id}
              empty="every order has reached its end state"
              columns={[
                { header: "Reference", cell: (order) => <span className="font-medium text-ink-900">{order.reference}</span> },
                { header: "Customer", cell: (order) => order.customer ?? `#${order.customer_id}` },
                { header: "State", cell: (order) => <Badge>{order.state}</Badge> },
                { header: "Total", cell: (order) => fromDecimalString(order.total) },
                {
                  header: "Actions",
                  align: "right",
                  cell: (order) => (
                    <ButtonLink size="sm" to={href("orders.operateOne", { orderId: order.id })}>
                      Operate
                    </ButtonLink>
                  ),
                },
              ]}
            />
        )}
      </DataState>
    </>
  );
}
