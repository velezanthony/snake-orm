/**
 * The lab's six reads as hooks. The mirror of `apps/lab/views.py`.
 *
 * The lab is the one domain where the payload is almost beside the point: its subject is the SQL,
 * and the tables are there to prove a query ran. So these hooks are thin on purpose — what they own
 * is WHICH question each page asks, and that is all there is to own.
 */

import { useResource, type Resource } from "~/core/hooks/useResource";
import { labService } from "~/domains/lab/service";
import type { LabPagination } from "~/domains/lab/types";
import type { SectionsResponse } from "~/core/http/shapes";

export function useLabIndex(): Resource<SectionsResponse> {
  return useResource(() => labService.index(), []);
}

export function useLabAggregates(): Resource<SectionsResponse> {
  return useResource(() => labService.aggregates(), []);
}

export function useLabSubqueries(): Resource<SectionsResponse> {
  return useResource(() => labService.subqueries(), []);
}

export function useLabJoins(): Resource<SectionsResponse> {
  return useResource(() => labService.joins(), []);
}

export function useLabExpressions(): Resource<SectionsResponse> {
  return useResource(() => labService.expressions(), []);
}

export function useLabPlans(): Resource<SectionsResponse> {
  return useResource(() => labService.plans(), []);
}

export function useLabAsync(): Resource<SectionsResponse> {
  return useResource(() => labService.asynchronous(), []);
}

/**
 * The paging experiment. `page` is ZERO-BASED and stays that way: the number in the URL is the number
 * the OFFSET is computed from, and adding one to it for the sake of looking friendlier would make
 * the page disagree with the SQL it exists to display.
 */
export function useLabPagination(page: number): Resource<LabPagination> {
  return useResource(() => labService.pagination(page), [page]);
}

/** The page whose whole output is the query log: an N+1 and a duplicate, provoked so the panel flags them. */
export function useLabProblems(): Resource<{ ran: boolean }> {
  return useResource(() => labService.problems(), []);
}
