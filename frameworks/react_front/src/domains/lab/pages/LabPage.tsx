/**
 * The six lab pages, and there is ONE component behind all of them.
 *
 * That is not a shortcut: the six endpoints answer in the same `sections` shape because the lab's
 * subject is the SQL rather than the data, and the tables are only there to prove a query ran. Six
 * near-identical components would be five copies of a layout waiting to drift apart, and the thing
 * a reader actually compares between these pages is the debug panel at the bottom — which is the
 * same panel every page of this demo has.
 */

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { SectionList } from "@organisms/SectionTable";
import type { Resource } from "~/core/hooks/useResource";
import type { SectionsResponse } from "~/core/http/shapes";
import {
  useLabAggregates,
  useLabIndex,
  useLabExpressions,
  useLabJoins,
  useLabAsync,
  useLabPlans,
  useLabSubqueries,
} from "~/domains/lab/viewmodels";

export function LabPage({
  title,
  lede,
  payload,
  children,
}: {
  title: string;
  lede: React.ReactNode;
  /** The resource, already asked for by the caller's hook. This component only lays it out. */
  payload: Resource<SectionsResponse>;
  children?: React.ReactNode;
}) {

  return (
    <>
      <PageHead title={title} lede={lede} />
      {children}
      <DataState resource={payload} loading="Running the queries…">
        {({ sections }) => <SectionList sections={sections} />}
      </DataState>
    </>
  );
}

export function LabIndexPage() {
  return (
    <LabPage
      title="Query lab"
      lede="Seven domains, twenty tables. Each experiment exercises a different part of the ORM, and the debug panel shows you the SQL every page generated."
      payload={useLabIndex()}
    />
  );
}

export function LabAggregatesPage() {
  return (
    <LabPage
      title="Lab · Aggregates"
      lede="Counts, sums and averages the ENGINE computes, typed into a dataclass on the way back."
      payload={useLabAggregates()}
    />
  );
}

export function LabSubqueriesPage() {
  return (
    <LabPage
      title="Lab · Subqueries"
      lede="Correlated subqueries as columns: a figure per row, computed beside the row it belongs to."
      payload={useLabSubqueries()}
    />
  );
}

export function LabExpressionsPage() {
  return (
    <LabPage
      title="Lab · Scalar functions"
      lede="Text, maths, JSON, case-insensitive matching and dates — computed in the ENGINE, not in a loop. Two engines out of three refuse the date functions, and the page prints the refusal instead of an empty table."
      payload={useLabExpressions()}
    />
  );
}

export function LabAsyncPage() {
  return (
    <LabPage
      title="Lab · The asynchronous seam"
      lede="The same queries, awaited. A SnakeQuery has no colour — it neither executes nor knows who will — so these selectors are the very objects the synchronous pages import, not copies of them."
      payload={useLabAsync()}
    />
  );
}

export function LabPlansPage() {
  return (
    <LabPage
      title="Lab · Plan and report"
      lede="EXPLAIN asks the engine to DESCRIBE a plan without running it — a prediction. The report underneath is a recording of what a page really issued. Reading one for the other optimises against the wrong thing."
      payload={useLabPlans()}
    />
  );
}

export function LabJoinsPage() {
  return (
    <LabPage
      title="Lab · Joins / include"
      lede="What include() emits, and what the same page costs without it."
      payload={useLabJoins()}
    />
  );
}
