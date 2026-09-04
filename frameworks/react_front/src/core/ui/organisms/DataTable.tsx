/**
 * A table declared by its COLUMNS, where the header and the cell travel together.
 *
 * That pairing is the whole reason this exists, and it is not about writing less. Written by hand, a
 * table declares its headers in one place and its cells in another, and nothing checks that the five
 * `<th>` match the five `<td>`: add a column, forget the header, and the result is a misaligned table
 * that renders happily and that no test in this repository can see. With `{ header, cell }` the two
 * halves are one object and the mistake is unwritable.
 *
 * WHAT IT DELIBERATELY DOES NOT DO. No sorting, no filtering, no pagination props. Those turn a
 * component into a small framework that fights you the moment a table is unusual, and this demo has
 * unusual tables. The escape hatch is total instead: `cell` returns whatever JSX it likes — a link, a
 * badge, a button — so nothing is out of reach. Paging stays next door in `Pager`, which is a
 * different question about a different thing.
 *
 * The accessibility props ride along because they are the ones that are easy to leave off and
 * invisible when you do: `tabIndex`/`role` on the scroller so a keyboard can reach the overflow, and
 * a `<caption>` a screen reader announces.
 */

import type { ReactNode } from "react";

export interface Column<Row> {
  readonly header: ReactNode;
  readonly cell: (row: Row) => ReactNode;
  /** `text-right` for the actions column, and little else. Kept narrow on purpose. */
  readonly align?: "right";
}

/**
 * `columns` is typed against `Row`, so a cell reading a field the row does not have is a compile
 * error rather than an `undefined` painted into the page.
 */
export function DataTable<Row>({
  label,
  caption,
  columns,
  rows,
  rowKey,
  empty,
  bare = false,
}: {
  /** What the scrollable region is called, for a screen reader. */
  label: string;
  /** One sentence saying what the table holds. Announced, not shown. */
  caption: string;
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  /**
   * The row's identity. Required, and never the array index: half the tables here are keyed on a
   * PAIR — inventory's `(warehouse, sku)` — and an index would look right until the list reorders.
   */
  rowKey: (row: Row) => string | number;
  /** What the empty state says, in the demo's own voice: it is rendered between dashes. */
  empty: string;
  /** Inside a card, the wrapper's own border doubles the card's. */
  bare?: boolean;
}) {
  return (
    <div
      className={bare ? "table-wrap rounded-none border-0" : "table-wrap"}
      tabIndex={0}
      role="region"
      aria-label={label}
    >
      <table className="table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column, index) => (
              // The position IS the identity of a column: two columns may share a header, and a
              // header is a ReactNode that need not be a string at all.
              <th scope="col" key={index} className={column.align === "right" ? "text-right" : undefined}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className="text-ink-400" colSpan={columns.length}>
                — {empty} —
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={rowKey(row)}>
                {columns.map((column, index) => (
                  <td key={index} className={column.align === "right" ? "text-right" : undefined}>
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
