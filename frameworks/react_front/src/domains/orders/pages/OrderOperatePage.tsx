/**
 * The page the row lock, the isolation level and the savepoint are reached from.
 *
 * Each button is ONE transaction that declares its isolation level before it reads anything, takes
 * the stock rows it needs under a row lock, and decides there. Where a button is missing, the reason
 * it is missing is printed in its place — which is the SSR page's rule and worth keeping: a greyed
 * button with no explanation is a dead end somebody has to go and read the code to understand.
 *
 * After every operation the page is RE-READ rather than patched from what came back. `reserve` and
 * `cancel` move the order AND the stock, so anything this component was holding is a screenshot of
 * a state that no longer exists.
 */

import * as fields from "~/core/lib/form";
import { useParams } from "react-router";

import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { Badge } from "@atoms/Badge";
import { Button, ButtonLink } from "@atoms/Button";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { Muted } from "@atoms/Text";
import { DescriptionList } from "@molecules/DescriptionList";
import { useAction } from "~/core/hooks/useAction";
import { fromDecimalString } from "~/core/lib/money";
import { ordersService } from "~/domains/orders/service";
import { useOrderOperation } from "~/domains/orders/viewmodels";

/** Why an operation is not offered from a given state, in the words the domain uses for it. */
const REFUSALS: Record<string, Record<string, string>> = {
  reserve: {
    reserved: "Already reserved: the units are held.",
    invoiced: "Already billed. Reserving again would hold units twice.",
    settled: "Settled and shipped. There is nothing left to hold.",
    cancelled: "Cancelled. Whatever it held has been given back.",
  },
  settle: {
    draft: "Nothing is held yet — reserve it first, or the money would arrive before the stock.",
    settled: "Already settled: the money arrived and it shipped.",
    cancelled: "Cancelled. There is nothing to charge for.",
  },
  cancel: {
    settled: "Settled and shipped. Cancelling would be a refund, which is a different operation.",
    cancelled: "Already cancelled.",
  },
};

export function OrderOperatePage() {
  const orderId = Number(useParams().orderId);

  const { sheet, operate: run } = useOrderOperation(orderId);
  const operate = useAction(run);

  return (
    <DataState resource={sheet} loading="Reading the order…">
      {({ order, lines }) => {
        const refusal = (operation: keyof typeof REFUSALS) => REFUSALS[operation]?.[order.state];

        return (
          <>
            <PageHead
              title={`Operate ${order.reference}`}
              lede="Each button below is one transaction that declares its isolation level before it reads anything, takes the stock rows it needs under a row lock, and decides there. Where a button is missing, the reason it is missing is printed in its place."
              actions={
                <ButtonLink size="sm" to={href("orders.detail", { orderId: order.id })}>
                  ← The order
                </ButtonLink>
              }
            />

            {operate.error !== null ? <Alert kind="error">{operate.error}</Alert> : null}

            <Card className="mb-6">
              <CardHead title="Where it stands" aside={<Badge>{order.state}</Badge>} />
              <CardBody>
                <DescriptionList
                  rows={[
                    ["Customer", order.customer ?? `#${order.customer_id}`],
                    ["Warehouse", order.warehouse ?? `#${order.warehouse_id}`],
                    ["Lines", lines.length],
                    ["Total", fromDecimalString(order.total)],
                    ["Invoice", order.invoice_id === null ? "— none attached —" : `#${order.invoice_id}`],
                  ]}
                />
              </CardBody>
            </Card>

            <Card>
              <CardHead
                title="Operations"
                sub="One transaction each. A refusal comes back as a status and a reason, never as a half-done write."
              />
              <CardBody className="space-y-4">
                <div>
                  {refusal("reserve") === undefined ? (
                    <Button
                      disabled={operate.pending}
                      onClick={() => void operate.run(() => ordersService.reserve(order.id))}
                    >
                      Reserve under a row lock
                    </Button>
                  ) : (
                    <Muted>Reserve — {refusal("reserve")}</Muted>
                  )}
                </div>

                <div>
                  {refusal("settle") === undefined ? (
                    <form
                      className="flex flex-wrap items-end gap-2"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const data = new FormData(event.currentTarget);
                        void operate.run(() =>
                          ordersService.settle(order.id, {
                            subscription_id: fields.number(data, "subscription_id"),
                            method: fields.text(data, "method") || "card",
                          }),
                        );
                      }}
                    >
                      <label className="label" htmlFor="subscription_id">
                        Subscription to bill
                        <input
                          className="input"
                          type="number"
                          id="subscription_id"
                          name="subscription_id"
                          min={1}
                          defaultValue={order.customer_id}
                          required
                        />
                      </label>
                      <Button type="submit" disabled={operate.pending}>
                        Settle through a savepoint
                      </Button>
                    </form>
                  ) : (
                    <Muted>Settle — {refusal("settle")}</Muted>
                  )}
                </div>

                <div>
                  {refusal("cancel") === undefined ? (
                    <Button
                      variant="danger"
                      disabled={operate.pending}
                      onClick={() => void operate.run(() => ordersService.cancel(order.id))}
                    >
                      Cancel and give back the hold
                    </Button>
                  ) : (
                    <Muted>Cancel — {refusal("cancel")}</Muted>
                  )}
                </div>
              </CardBody>
            </Card>
          </>
        );
      }}
    </DataState>
  );
}
