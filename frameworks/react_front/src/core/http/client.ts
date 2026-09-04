/**
 * The ONE place this app performs a request. Every service below it goes through `request`.
 *
 * What it centralises is not "fetch with less typing". It is four decisions that must be the same
 * everywhere or the app is wrong somewhere:
 *
 *  1. `credentials: "include"` — the session cookie rides on every call, including the reads. Miss
 *     it on one endpoint and that endpoint is anonymous while the rest of the app is logged in.
 *  2. A non-2xx is an EXCEPTION carrying the status and the API's own `detail`. A component that
 *     forgets to check `response.ok` renders "undefined" into the page; one that forgets to catch
 *     gets a boundary. The failure is loud either way.
 *  3. The `snakeorm` debug block is peeled off the payload and handed to a listener. It rides in
 *     EVERY JSON response — the demos turn it on with the `envelope` channel — and a component that
 *     had to step around it would be a component that knows about the ORM's debug tooling.
 *  4. The URL is built by `apiUrl`, so switching backend is a config change and never a service one.
 */

import { apiUrl } from "~/config/backends";
import type { QueryLog } from "~/core/http/envelope";

/** A non-2xx answer, with what the API said about it. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    /** The `detail` the three demos agree on (`bad_credentials`, `not_found`, `forbidden`, ...). */
    readonly detail: string,
  ) {
    super(`${status} ${detail}`);
    this.name = "ApiError";
  }
}

/** True when the API said "no session" — the one status the app reacts to globally. */
export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

type QueryLogListener = (log: QueryLog, path: string) => void;

const listeners = new Set<QueryLogListener>();

/**
 * Subscribes to the SQL every request ran. Returns the unsubscribe, so an effect can just return it.
 *
 * This is the debug panel's feed. The SSR demos inject theirs into the HTML because the server is
 * what renders the page; here the page is already on screen when the SQL happens, so the panel
 * listens instead.
 */
export function onQueryLog(listener: QueryLogListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

interface Envelope {
  snakeorm?: QueryLog;
}

function peelDebugEnvelope<T>(payload: T, path: string): T {
  if (payload === null || typeof payload !== "object") return payload;
  const { snakeorm, ...rest } = payload as Envelope & Record<string, unknown>;
  if (snakeorm === undefined) return payload;
  for (const listener of listeners) listener(snakeorm, path);
  return rest as T;
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // An error page that is not JSON (a Django 500 in DEBUG, an nginx 502). The status is the
    // only thing that survives, and inventing a message would bury it.
  }
  return response.statusText || "request failed";
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  /** Serialised as JSON. `undefined` sends no body at all, which is what a GET wants. */
  body?: unknown;
  signal?: AbortSignal;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;

  const response = await fetch(apiUrl(path), {
    method,
    // The reason this file exists. See the note at the top.
    credentials: "include",
    headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  if (!response.ok) throw new ApiError(response.status, await readDetail(response));
  if (response.status === 204) return undefined as T;

  const payload = (await response.json()) as T;
  return peelDebugEnvelope(payload, path);
}

/**
 * A read whose payload is a LIST, normalised across the two shapes the API can send it in.
 *
 * This is not defensive coding for its own sake. Nine of the ten domains hand back a bare JSON
 * array — `Response([tag_dict(t) for t in ...])` — and what turns it into `{"data": [...]}` is the
 * ORM's debug middleware, which cannot hang a `snakeorm` block off an array and wraps it to get an
 * object to hang it on. So the shape of every list endpoint in this demo depends on whether the
 * `envelope` channel is switched on.
 *
 * A client that read `.data` would work in development and return `undefined` for every list the
 * moment somebody ran the demo with the panel off — which is exactly how it would be run in front
 * of an audience. Asking the question once, here, is the whole fix.
 */
export async function requestList<T>(path: string, options: RequestOptions = {}): Promise<T[]> {
  const payload = await request<T[] | { data: T[] }>(path, options);
  if (Array.isArray(payload)) return payload;
  return payload.data ?? [];
}

/** Builds a query string, dropping the keys with nothing in them. */
export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const pairs = Object.entries(params).filter(
    (entry): entry is [string, string | number | boolean] =>
      entry[1] !== undefined && entry[1] !== null && entry[1] !== "",
  );
  if (pairs.length === 0) return "";
  return `?${pairs.map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`).join("&")}`;
}

/**
 * The URL of a CSV export, for an `<a href>` rather than a `fetch`.
 *
 * The three demos stream their CSVs, and the browser is better at receiving a stream than this app
 * is: a link gets a progress indicator, a Save dialog and a cancel button for free. Pulling the
 * whole body into memory to hand back a blob would trade all three for nothing.
 */
export function exportUrl(path: string, params: Record<string, string | number | undefined> = {}): string {
  return apiUrl(`${path}${query(params)}`);
}
