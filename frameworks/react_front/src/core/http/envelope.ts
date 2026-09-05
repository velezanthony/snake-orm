/**
 * The shapes the three APIs agree on. They agree because they SHARE the code that builds them:
 * `frameworks/shared/dto/` serialises every domain once, and Django, Flask and FastAPI each hand
 * that dict to their own framework. So these are not three sets of types with a common subset —
 * they are one set, written down on the client side of the wire.
 *
 * Money arrives as a STRING and is kept as one. `total: "36708.40"` is a `Decimal` on the Python
 * side, and the only thing `Number("36708.40")` can add to it is a rounding error nobody asked for.
 * The one place that is not true is billing, which counts in whole CENTS on purpose — an integer
 * there is exact, and the formatting is the view's problem.
 */

/** The `snakeorm` block every JSON response carries while the `envelope` channel is on. */
export interface QueryLog {
  summary: string;
  count: number;
  total_ms: number;
  db_ms: number;
  /**
   * NULLABLE, and `report.py` says so: the wall clock is measured by the middleware AROUND the app,
   * so a report with no request behind it has neither the wall nor the `app_ms` derived from it.
   * Typed as a plain `number` this was a `.toFixed` on `null` waiting for the first sidecar.
   */
  wall_ms: number | null;
  app_ms: number | null;
  warnings: string[];
  index_hints: string[];
  queries: QueryEntry[];
}

export interface QueryEntry {
  n: number;
  ms: number;
  kind: string;
  sql: string;
  params: unknown[];
  rows: number;
  origin: { file: string; line: number; function: string } | null;
}

