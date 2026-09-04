/**
 * `DataTable` types its cells against the ROW, asserted by the compiler.
 *
 * The claim this file pins is the one that justifies the component's existence: a cell cannot read a
 * field the row does not have. Written by hand — `<td>{order.totl}</td>` — that mistake renders the
 * word `undefined` into the page and no test in this repository can see it, because nothing here
 * asserts against rendered HTML.
 *
 * `tsc` is the runner. `@ts-expect-error` fails the build if the line it guards starts compiling.
 */

import { DataTable, type Column } from "@organisms/DataTable";

interface Order {
  id: number;
  reference: string;
  total: string;
}

const rows: Order[] = [];

// --- what must compile ---------------------------------------------------------------------------

const columns: Column<Order>[] = [
  { header: "Reference", cell: (order) => order.reference },
  { header: "Total", cell: (order) => order.total, align: "right" },
];

export const _table = (
  <DataTable
    label="Orders"
    caption="Every order."
    rows={rows}
    rowKey={(order) => order.id}
    columns={columns}
    empty="no orders"
  />
);

// --- what must NOT compile -------------------------------------------------------------------------

// @ts-expect-error the field is `total`, not `totl` — the mistake that renders "undefined"
const _typo: Column<Order>[] = [{ header: "Total", cell: (order) => order.totl }];

// @ts-expect-error `align` is a closed set: there is no "centre" in this stylesheet
const _align: Column<Order>[] = [{ header: "x", cell: () => null, align: "centre" }];

// @ts-expect-error a header with no cell is half a column, and half a column is the drift itself
const _halfColumn: Column<Order>[] = [{ header: "Total" }];
