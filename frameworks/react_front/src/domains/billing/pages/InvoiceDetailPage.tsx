/**
 * One invoice and the payments against it. TWO statements, and the second is not a join.
 */

import { useParams } from "react-router";

import { href } from "~/config/href";
import { StateBadge } from "@atoms/Badge";
import { ButtonLink } from "@atoms/Button";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { DescriptionList } from "@molecules/DescriptionList";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { fromCents } from "~/core/lib/money";
import { useInvoiceSheet } from "~/domains/billing/viewmodels";

export function InvoiceDetailPage() {
  const invoiceId = Number(useParams().invoiceId);
  const sheet = useInvoiceSheet(invoiceId);

  return (
    <DataState resource={sheet} loading="Reading the invoice…">
      {({ invoice, payments }) => (
        <>
          <PageHead
            title={`Invoice ${invoice.id}`}
            lede={`The to-many of this page: ${payments.length} payment${payments.length === 1 ? "" : "s"} against one invoice, loaded as a second statement rather than as a join, because a to-many in the same SELECT would multiply the invoice row by its payments.`}
            actions={
              <ButtonLink size="sm" to={href("billing.list")}>
                ← Every invoice
              </ButtonLink>
            }
          />

          <Card className="mb-6">
            <CardHead
              title="The invoice"
              sub="Three to-one hops, flattened onto one row by the listing this came from."
              aside={<StateBadge on={invoice.paid} yes="Paid" no="Unpaid" />}
            />
            <CardBody>
              <DescriptionList
                rows={[
                  ["Customer", invoice.customer],
                  ["Plan", `${invoice.plan} · ${fromCents(invoice.plan_price_cents)}`],
                  ["Amount", fromCents(invoice.amount_cents)],
                  ["Issued", invoice.issued_at],
                  ["Subscription", `#${invoice.subscription_id}`],
                ]}
              />
            </CardBody>
          </Card>

          <Card>
            <CardHead title="Payments" sub="The second statement — never a join, for the reason above." />
            <DataTable
              bare
              label="Payments"
              caption="Every payment recorded against this invoice."
              rows={payments}
              rowKey={(payment) => payment.id}
              empty="nothing paid yet"
              columns={[
                { header: "#", cell: (p) => <span className="muted">{p.id}</span> },
                { header: "Amount", cell: (p) => fromCents(p.amount_cents) },
                { header: "Method", cell: (p) => <span className="muted">{p.method}</span> },
                { header: "Paid", cell: (p) => <span className="muted">{p.paid_at}</span> },
              ]}
            />
          </Card>
        </>
      )}
    </DataState>
  );
}
