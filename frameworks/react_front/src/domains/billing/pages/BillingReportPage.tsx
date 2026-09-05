/**
 * Three statements, and not one of them grows with the number of invoices.
 *
 * Each table says which part of the ORM produced it, because a number with no provenance teaches
 * nothing — the same line every report page in these demos carries.
 */

import { Card, CardBody, CardHead } from "@molecules/Card";
import { DescriptionList } from "@molecules/DescriptionList";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { fromCents } from "~/core/lib/money";
import { useBillingReport } from "~/domains/billing/viewmodels";

export function BillingReportPage() {
  const report = useBillingReport();

  return (
    <>
      <PageHead
        title="Billing report"
        lede="Three statements, and not one of them grows with the number of invoices. Each table says which part of the ORM produced it, because a number with no provenance teaches nothing."
      />

      <DataState resource={report} loading="Adding it up…">
        {(data) => (
          <>
            <Card className="mb-6">
              <CardHead title="Outstanding" sub="Two figures from one aggregate — a COUNT and a SUM over the unpaid." />
              <CardBody>
                <DescriptionList
                  rows={[["Unpaid invoices", data.unpaid_count], ["Owed", fromCents(data.unpaid_cents)]]}
                />
              </CardBody>
            </Card>

            <Card className="mb-6">
              <CardHead title="Plans" sub="annotate: a correlated COUNT of subscriptions beside each plan." />
              <DataTable
                bare
                label="Plans"
                caption="Every plan with its price and how many are subscribed to it."
                rows={data.plans}
                rowKey={(plan) => plan.id}
                empty="no plans"
                columns={[
                  { header: "Plan", cell: (p) => <span className="font-medium text-ink-900">{p.name}</span> },
                  { header: "Price", cell: (p) => fromCents(p.price_cents) },
                  { header: "Subscriptions", cell: (p) => <span className="muted">{p.subscription_count}</span> },
                ]}
              />
            </Card>

            <Card className="mb-6">
              <CardHead title="Revenue per plan" sub="GROUP BY + HAVING over whole CENTS — an integer, so it is exact." />
              <DataTable
                bare
                label="Revenue per plan"
                caption="What each plan has invoiced, and over how many invoices."
                rows={data.revenue}
                rowKey={(row) => row.plan}
                empty="nothing invoiced"
                columns={[
                  { header: "Plan", cell: (r) => <span className="font-medium text-ink-900">{r.plan}</span> },
                  { header: "Invoices", cell: (r) => <span className="muted">{r.invoice_count}</span> },
                  { header: "Revenue", cell: (r) => fromCents(r.revenue_cents) },
                ]}
              />
            </Card>

            <Card>
              <CardHead title="Overdue" sub="A due date computed in SQL — the direction a date only ever moves forward." />
              <DataTable
                bare
                label="Overdue invoices"
                caption="The invoices past their due date, with how much of each has been collected."
                rows={data.overdue}
                rowKey={(row) => row.invoice_id}
                empty="nothing overdue"
                columns={[
                  { header: "Invoice", cell: (r) => <span className="font-medium text-ink-900">{r.invoice_id}</span> },
                  { header: "Amount", cell: (r) => fromCents(r.amount_cents) },
                  { header: "Due", cell: (r) => <span className="muted">{r.due}</span> },
                  { header: "Collected", cell: (r) => <span className="muted">{r.collected}</span> },
                ]}
              />
            </Card>
          </>
        )}
      </DataState>
    </>
  );
}
