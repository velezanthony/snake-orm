/** Every order, paginated: the rows and one COUNT, whatever the page. */


import { href } from "~/config/href";

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { Badge } from "@atoms/Badge";
import { ButtonLink } from "@atoms/Button";
import { Pager } from "@molecules/Pager";
import { usePageParam } from "~/core/hooks/usePageParam";
import { fromDecimalString } from "~/core/lib/money";
import { useOrderPage } from "~/domains/orders/viewmodels";

/** `draft` is the state all three operations are reachable from, so it is the one that stands out. */
function stateTone(state: string): "ok" | "muted" {
  return state === "settled" || state === "invoiced" ? "ok" : "muted";
}

export function OrderListPage() {
  const [page, setPage] = usePageParam();
  const orders = useOrderPage(page);

  return (
    <>
      <PageHead
        title="Orders"
        lede="A page of orders with the customer and the warehouse already joined: one SELECT and one COUNT for the pager, whatever the size of the page."
      />

      <DataState resource={orders} loading="Reading the orders…">
        {(payload) => (
          <>
            <DataTable
              label="Orders"
              caption="Every order with its customer, warehouse, state and total."
              rows={payload.rows}
              rowKey={(order) => order.id}
              empty="no orders"
              columns={[
                {
                  header: "Reference",
                  cell: (order) => (
                    <a className="font-medium text-ink-900 hover:text-brand-700" href={href("orders.detail", { orderId: order.id })}>
                      {order.reference}
                    </a>
                  ),
                },
                { header: "Customer", cell: (order) => order.customer ?? `#${order.customer_id}` },
                { header: "Warehouse", cell: (order) => <span className="muted">{order.warehouse ?? `#${order.warehouse_id}`}</span> },
                { header: "State", cell: (order) => <Badge tone={stateTone(order.state)}>{order.state}</Badge> },
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

            <Pager page={payload.page} pages={payload.pages} total={payload.total} onPage={setPage} />
          </>
        )}
      </DataState>
    </>
  );
}
