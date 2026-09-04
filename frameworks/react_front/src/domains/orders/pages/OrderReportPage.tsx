/**
 * Five questions, five different parts of the ORM, one page.
 *
 * Every table says which part produced it, because a number with no provenance teaches nothing.
 */

import { href } from "~/config/href";

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { ButtonLink } from "@atoms/Button";
import { Card, CardHead } from "@molecules/Card";
import { fromDecimalString } from "~/core/lib/money";
import { useOrderReport } from "~/domains/orders/viewmodels";

export function OrderReportPage() {
  const report = useOrderReport();

  return (
    <>
      <PageHead
        title="Orders report"
        lede="Five questions, five different parts of the ORM, one page. Every table says which part produced it, and none of them grows with the number of orders."
      />

      <DataState resource={report} loading="Adding it up…">
        {({ customers, states }) => (
          <>
            <Card className="mb-6">
              <CardHead
                title="Orders per state"
                sub="GROUP BY over the state column, with a SUM of the totals beside each count."
              />
              <DataTable
                bare
                label="Orders per state"
                caption="How many orders sit in each state, and what they add up to."
                rows={states}
                rowKey={(row) => row.state}
                empty="no orders"
                columns={[
                  { header: "State", cell: (r) => <span className="font-medium text-ink-900">{r.state}</span> },
                  { header: "Orders", cell: (r) => <span className="muted">{r.orders}</span> },
                  { header: "Total", cell: (r) => fromDecimalString(r.total) },
                ]}
              />
            </Card>

            <Card>
              <CardHead
                title="Customers"
                sub="annotate: a correlated COUNT and SUM computed beside each customer, in one statement."
              />
              <DataTable
                bare
                label="Customers"
                caption="Everybody who could have ordered, with what they have ordered."
                rows={customers}
                rowKey={(customer) => customer.id}
                empty="nobody yet"
                columns={[
                  {
                    header: "Customer",
                    cell: (c) => (
                      <a className="font-medium text-ink-900 hover:text-brand-700" href={href("orders.customer", { customerId: c.id })}>
                        {c.username}
                      </a>
                    ),
                  },
                  { header: "Orders", cell: (c) => <span className="muted">{c.order_count}</span> },
                  // `"None"` is what `str(None)` gives for a customer who has never ordered.
                  // `fromDecimalString` is where that becomes a dash instead of a word.
                  { header: "Spent", cell: (c) => fromDecimalString(c.ordered_total) },
                  {
                    header: "Actions",
                    align: "right",
                    cell: (c) => (
                      <ButtonLink size="sm" to={href("orders.customer", { customerId: c.id })}>
                        Sheet
                      </ButtonLink>
                    ),
                  },
                ]}
              />
            </Card>
          </>
        )}
      </DataState>
    </>
  );
}
