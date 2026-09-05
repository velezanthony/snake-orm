/**
 * The lab's nine routes. The mirror of `apps/lab/urls.py`.
 *
 * Seven of them share ONE component, and that is the section's shape rather than a shortcut: the nine
 * endpoints answer in the same `sections` payload because the lab's subject is the SQL, and the
 * tables are only there to prove a query ran. Nine near-identical components would be eight copies of
 * a layout waiting to drift.
 */

import { defineDomain } from "~/core/routing/domain";
import {
  LabAggregatesPage,
  LabAsyncPage,
  LabExpressionsPage,
  LabIndexPage,
  LabPlansPage,
  LabJoinsPage,
  LabSubqueriesPage,
} from "~/domains/lab/pages/LabPage";
import { LabPaginationPage } from "~/domains/lab/pages/LabPaginationPage";
import { LabProblemsPage } from "~/domains/lab/pages/LabProblemsPage";

export const labRoutes = defineDomain("/lab", {
  list: { segment: "", element: <LabIndexPage />, nav: "Seeded volume" },
  aggregates: { segment: "aggregates", element: <LabAggregatesPage />, nav: "Aggregates" },
  subqueries: { segment: "subqueries", element: <LabSubqueriesPage />, nav: "Subqueries" },
  joins: { segment: "joins", element: <LabJoinsPage />, nav: "Joins / include" },
  expressions: { segment: "expressions", element: <LabExpressionsPage />, nav: "Scalar functions" },
  plans: { segment: "plans", element: <LabPlansPage />, nav: "Plan and report" },
  asynchronous: { segment: "asynchronous", element: <LabAsyncPage />, nav: "Async seam" },
  pagination: { segment: "pagination", element: <LabPaginationPage />, nav: "Pagination" },
  problems: { segment: "problems", element: <LabProblemsPage />, nav: "Problems on purpose" },
});
