/**
 * A titled table with its provenance note, rendered from the positional shape the API sends.
 *
 * `columns` and `rows` are parallel — a header list and a list of cell lists — so this component
 * knows nothing at all about what it is showing. That is what lets the six lab pages and the report
 * pages share it: the domain decided what the table means, and the client only has to lay it out.
 */

import { DataTable, type Column } from "@organisms/DataTable";
import { Card, CardHead } from "@molecules/Card";
import type { Section } from "~/core/http/shapes";

/** A lab row: its cells, and the position that is the only identity it has. */
interface PositionalRow {
  cells: unknown[];
  index: number;
}

/**
 * One cell of a lab table, which is `unknown` because the payload is a table and not a shape.
 *
 * The `String()` at the end is narrowed to the primitives on purpose: an object reaching it would
 * print `[object Object]`, which is the linter's finding and a real one — the lab does answer nested
 * values, and JSON is what a reader can act on.
 */
function cell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "bigint") return value.toString();
  return JSON.stringify(value) ?? "—";
}

export function SectionTable({ section }: { section: Section }) {
  return (
    <Card className="mb-6">
      <CardHead title={section.title} sub={section.note} />
      <DataTable
        bare
        label={section.title}
        caption={section.note || section.title}
        rows={section.rows.map((cells, index) => ({ cells, index }))}
        // These rows are POSITIONAL and have no key of their own — the lab's payload is a table, not
        // a list of entities — so the position is the identity, said out loud instead of hidden in
        // an array index.
        rowKey={(row) => row.index}
        empty="nothing to show"
        columns={section.columns.map((header, column): Column<PositionalRow> => ({
          header,
          cell: (row) => cell(row.cells[column]),
        }))}
      />
    </Card>
  );
}

export function SectionList({ sections }: { sections: Section[] }) {
  return (
    <>
      {sections.map((section) => (
        <SectionTable key={section.title} section={section} />
      ))}
    </>
  );
}
