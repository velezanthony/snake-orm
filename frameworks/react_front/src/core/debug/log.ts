/**
 * The SESSION's debug tape: every `snakeorm` envelope this client has peeled, newest first.
 *
 * WHY IT IS A MODULE AND NOT A CONTEXT. The tape has to record whether or not anything is looking
 * at it — the dock is shut most of the time, and a request fired from a page you have already left
 * is exactly the one you want to find later. A provider would tie the recording to a mounted tree
 * and to a render; `onQueryLog` already publishes from outside React, so the store lives outside
 * React too and components read it through `useSyncExternalStore`.
 *
 * The subscription is taken at import and never dropped. That is the point: one listener for the
 * app's life, so no page can forget to register and no unmount can lose a page's worth of SQL.
 */

import { useSyncExternalStore } from "react";

import { onQueryLog } from "~/core/http/client";
import type { QueryLog } from "~/core/http/envelope";

/** One recorded response: the envelope, plus who asked for it and when. */
export interface DebugEntry {
  /** Monotonic across the session, so the tape numbers requests the way the ORM numbers queries. */
  readonly id: number;
  readonly path: string;
  /** Epoch milliseconds. */
  readonly at: number;
  readonly log: QueryLog;
}

export interface DebugLogState {
  /** Newest first: the thing you just clicked is the thing you are looking for. */
  readonly entries: readonly DebugEntry[];
  /** How many entries the cap threw away. Shown on screen — see the note on the cap. */
  readonly dropped: number;
}

/**
 * The cap, and it is announced rather than silent.
 *
 * A tape that quietly forgets reads as "this is everything", which is the same lie the panel this
 * replaced told by picking fields. So the dock prints the discarded count whenever it is not zero.
 */
export const DEBUG_LOG_LIMIT = 200;

const EMPTY: DebugLogState = { entries: [], dropped: 0 };

let state: DebugLogState = EMPTY;
let nextId = 1;

const subscribers = new Set<() => void>();

function publish(next: DebugLogState): void {
  state = next;
  for (const notify of subscribers) notify();
}

function record(log: QueryLog, path: string): void {
  const entry: DebugEntry = { id: nextId++, path, at: Date.now(), log };
  const entries = [entry, ...state.entries];
  const overflow = Math.max(0, entries.length - DEBUG_LOG_LIMIT);
  publish({ entries: entries.slice(0, DEBUG_LOG_LIMIT), dropped: state.dropped + overflow });
}

onQueryLog(record);

function subscribe(notify: () => void): () => void {
  subscribers.add(notify);
  return () => {
    subscribers.delete(notify);
  };
}

// `useSyncExternalStore` compares snapshots by identity, so this must be the stored object and never
// a fresh one — returning a new array here is an infinite render loop.
function getSnapshot(): DebugLogState {
  return state;
}

export function useDebugLog(): DebugLogState {
  return useSyncExternalStore(subscribe, getSnapshot);
}

/** Starts the tape over, discarded count included — "cleared" means there is nothing to account for. */
export function clearDebugLog(): void {
  publish(EMPTY);
}
