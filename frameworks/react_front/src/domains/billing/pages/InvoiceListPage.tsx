/**
 * The deepest listing in the demo: every row flattens THREE to-one hops as LEFT JOINs on one SELECT.
 */

import { href } from "~/config/href";
import { StateBadge } from "@atoms/Badge";
import { PageHead } from "@molecules/PageHead";
import { Pager } from "@molecules/Pager";
import { usePageParam } from "~/core/hooks/usePageParam";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { fromCents } from "~/core/lib/money";
import { useInvoicePage } from "~/domains/billing/viewmodels";

export function InvoiceListPage() {
  const [page, setPage] = usePageParam();
  const invoices = useInvoicePage(page);

  return (
    <>
      <PageHead
        title="Invoices"
        lede="The deepest listing in the demo: every row flattens THREE to-one hops — invoice → subscription → plan and → user — as LEFT JOINs on the same SELECT. Two statements a page, whatever the filter: the rows and the count."
      />

      <DataState resource={invoices} loading="Reading the ledger…">
        {(payload) => (
          <>
            <DataTable
              label="Invoices"
              caption="Every invoice with its subscription, its plan and its customer, on one row."
              rows={payload.rows}
              rowKey={(invoice) => invoice.id}
              empty="no invoices"
              columns={[
                {
                  header: "#",
                  cell: (invoice) => (
                    <a className="font-medium text-ink-900 hover:text-brand-700" href={href("billing.detail", { invoiceId: invoice.id })}>
                      {invoice.id}
                    </a>
                  ),
                },
                { header: "Customer", cell: (invoice) => invoice.customer },
                { header: "Plan", cell: (invoice) => <span className="muted">{invoice.plan}</span> },
                { header: "Amount", cell: (invoice) => fromCents(invoice.amount_cents) },
                { header: "State", cell: (invoice) => <StateBadge on={invoice.paid} yes="Paid" no="Unpaid" /> },
                { header: "Issued", cell: (invoice) => <span className="muted">{invoice.issued_at}</span> },
              ]}
            />

            <Pager page={payload.page} pages={payload.pages} total={payload.total} onPage={setPage} />
          </>
        )}
      </DataState>
    </>
  );
}
