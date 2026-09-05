/**
 * The floating button, and behind it the whole session's SQL.
 *
 * TWO READERS, ONE VIEW, and the design answers to both. For MONITORING, every entry's summary line
 * carries the cost — count, db time, app time, and whether the ORM shouted — so the tape can be
 * scanned without opening anything. For anyone holding POSTMAN next to this, the body under that
 * line is the envelope verbatim, so what is on screen is what is on the wire.
 *
 * The summary line reads a handful of fields; the body under it reads NONE — it prints whatever
 * came. That is the split that keeps the scan line useful without letting it decide what exists.
 *
 * It is a LOG and not a snapshot of the last request. The three SSR demos render their panel with
 * the page because the server still has the query log in hand; here the page outlives many
 * requests, and the question that gets asked in front of an audience is "what did the last three
 * things I clicked cost", which a single-request panel cannot answer.
 *
 * A `<dialog>` opened with `showModal()`: focus trap, Escape and a backdrop, none of them written
 * here.
 */

import { useEffect, useRef, useState } from "react";

import { Button } from "@atoms/Button";
import { DEBUG_LOG_LIMIT, clearDebugLog, useDebugLog, type DebugEntry } from "~/core/debug/log";
import { JsonNode } from "~/core/debug/JsonNode";

/** `wall_ms` and `app_ms` are null when nobody measured the request. Say so rather than crash. */
function ms(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}ms`;
}

function clock(at: number): string {
  return new Date(at).toLocaleTimeString();
}

function EntryRow({ entry }: { entry: DebugEntry }) {
  const { log } = entry;
  const shouts = log.warnings.length + log.index_hints.length;

  return (
    <details className="border-b border-ink-200 px-4 py-2 last:border-b-0">
      <summary className="cursor-pointer text-xs">
        <span className="text-ink-400">
          #{entry.id} · {clock(entry.at)}
        </span>{" "}
        <span className="font-mono text-ink-900">{entry.path}</span>{" "}
        <span className="text-ink-600">
          · {log.summary} · db {ms(log.db_ms)} · app {ms(log.app_ms)}
        </span>
        {shouts > 0 ? (
          <span className="ml-2 rounded-full bg-red-50 px-2 py-0.5 text-red-700">
            {log.warnings.length} warnings · {log.index_hints.length} index hints
          </span>
        ) : null}
      </summary>

      <div className="mt-2">
        <JsonNode defaultOpen name="snakeorm" value={log} />
      </div>
    </details>
  );
}

export function DebugDock() {
  const { entries, dropped } = useDebugLog();
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const node = dialog.current;
    if (node === null) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);

  // Nothing has been recorded yet, so there is nothing to float over the page for.
  if (entries.length === 0) return null;

  return (
    <>
      {/* Keeps the last line of the page scrollable clear of the button instead of under it. */}
      <div aria-hidden="true" className="h-20" />

      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        className="btn btn-primary btn-sm fixed right-4 bottom-4 z-40 shadow-lg"
        onClick={() => setOpen(true)}
        type="button"
      >
        SnakeORM log <span className="badge badge-ok">{entries.length}</span>
      </button>

      <dialog
        aria-labelledby="debug-dock-title"
        className="m-auto w-[min(64rem,94vw)] bg-transparent p-0 backdrop:bg-black/40"
        onClose={() => setOpen(false)}
        ref={dialog}
      >
        <section className="card flex max-h-[85vh] flex-col">
          <header className="card-head shrink-0">
            <div>
              <h2 className="card-title" id="debug-dock-title">
                SnakeORM · this session
              </h2>
              <p className="card-sub">
                Every response that carried a debug envelope, newest first. The line is the cost; what
                is under it is the payload exactly as it arrived.
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button onClick={clearDebugLog} size="sm" variant="ghost">
                Clear
              </Button>
              <Button onClick={() => setOpen(false)} size="sm" variant="ghost">
                Close
              </Button>
            </div>
          </header>

          {dropped > 0 ? (
            <p className="alert alert-error m-4 shrink-0">
              {dropped} older entries were dropped: the tape keeps the last {DEBUG_LOG_LIMIT}.
            </p>
          ) : null}

          <div className="min-h-0 flex-1 overflow-y-auto">
            {entries.map((entry) => (
              <EntryRow entry={entry} key={entry.id} />
            ))}
          </div>
        </section>
      </dialog>
    </>
  );
}
