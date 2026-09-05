/**
 * The confirmation, and the refusal is shown BEFORE the button is pressed.
 *
 * That is the SSR page's decision and it is the interesting half: the foreign key from the lines is
 * RESTRICT, so an order that has any cannot be deleted, and what somebody looking at it needs to
 * hear is that CANCELLING is the operation they actually want — not a button that fails.
 *
 * The lines are NAMED and not counted, which the shared viewmodel argues for: an order has a handful
 * of them, and which SKUs they are is the answer somebody wants before pressing something they
 * cannot undo.
 *
 * The API still refuses on its own with a 409, and that refusal is rendered too rather than hidden:
 * an order can gain a line between this page being drawn and the button being pressed.
 */

import { useNavigate, useParams } from "react-router";

import { href } from "~/config/href";
import { useAction } from "~/core/hooks/useAction";
import { Button, ButtonLink } from "@atoms/Button";
import { Alert } from "@molecules/Alert";
import { ArticleCard, CardBody, CardFoot, CardHead } from "@molecules/Card";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { orderWrites, useOrderSheet } from "~/domains/orders/viewmodels";

export function OrderDeletePage() {
  const orderId = Number(useParams().orderId);
  const navigate = useNavigate();

  const sheet = useOrderSheet(orderId);

  const remove = useAction(async () => {
    await orderWrites.remove(orderId);
    await navigate(href("orders.list"), { replace: true });
  });

  return (
    <DataState resource={sheet} loading="Reading the order…">
      {({ order, lines }) => (
        <ArticleCard className="max-w-lg">
          <CardHead title={<span className="text-xl">Delete {order.reference}</span>} />
          <CardBody className="text-ink-600">
            {remove.error !== null ? <Alert kind="error">{remove.error}</Alert> : null}
            {lines.length === 0 ? (
              <>Nothing hangs off this order, so the row can go. This cannot be undone.</>
            ) : (
              <>
                This order has {lines.length} line{lines.length === 1 ? "" : "s"}, and the foreign key
                from them is RESTRICT — the database will refuse. <strong>Cancel it instead</strong>,
                which is the operation that gives back what it was holding.
              </>
            )}
          </CardBody>

          {lines.length > 0 ? (
            <DataTable
              bare
              label="What would go with it"
              caption="The lines of this order, named rather than counted."
              rows={lines}
              rowKey={(line) => `${line.order_id}-${line.sku_id}`}
              empty="no lines"
              columns={[
                { header: "SKU", cell: (line) => line.sku ?? `#${line.sku_id}` },
                { header: "Units", cell: (line) => line.quantity },
              ]}
            />
          ) : null}

          <CardFoot>
            <Button
              variant="danger"
              disabled={remove.pending || lines.length > 0}
              onClick={() => void remove.run()}
            >
              {remove.pending ? "Deleting…" : "Yes, delete it"}
            </Button>
            <ButtonLink to={href("orders.operateOne", { orderId })}>Cancel it instead</ButtonLink>
            <ButtonLink to={href("orders.detail", { orderId })}>Back</ButtonLink>
          </CardFoot>
        </ArticleCard>
      )}
    </DataState>
  );
}
