/**
 * The query lab: the six pages that exist to SHOW the SQL rather than to serve a domain.
 *
 * Every one of them answers a payload whose interesting half is the `snakeorm` block the HTTP layer
 * peels off — so these pages read thin and the debug panel reads thick, which is the arrangement
 * the lab is about.
 */

import { query, request } from "~/core/http/client";
import type { SectionsResponse } from "~/core/http/shapes";
import type { LabPagination } from "~/domains/lab/types";

export type LabPayload = SectionsResponse;

export const labService = {
  index: () => request<LabPayload>("/api/lab"),
  aggregates: () => request<LabPayload>("/api/lab/aggregates"),
  subqueries: () => request<LabPayload>("/api/lab/subqueries"),
  joins: () => request<LabPayload>("/api/lab/joins"),
  expressions: () => request<LabPayload>("/api/lab/expressions"),
  plans: () => request<LabPayload>("/api/lab/plans"),
  asynchronous: () => request<LabPayload>("/api/lab/asynchronous"),
  pagination: (page: number) => request<LabPagination>(`/api/lab/pagination${query({ page })}`),
  /**
   * The one lab endpoint that answers `{ ran: true }` and nothing else, on purpose.
   *
   * Its whole output is the SQL it ran — an N+1 and a duplicated query, provoked so the panel can
   * flag them. There is no table to draw, and drawing one would hide the point.
   */
  problems: () => request<{ ran: boolean }>("/api/lab/problems"),
};
