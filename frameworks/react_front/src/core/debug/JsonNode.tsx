/**
 * The envelope printed AS IT ARRIVED — one `<details>` per branch, all the way down.
 *
 * It walks the VALUE and never the type, which is the whole reason it exists. The panel this
 * replaced named six fields by hand, so `warnings`, `index_hints` and `params` were on the wire and
 * off the screen, and anything the ORM adds tomorrow would join them without a single test going
 * red. Rendering whatever came back cannot drift.
 *
 * `<details>` and not a JSON viewer library: it collapses, it takes the keyboard and it needs no
 * expanded-state to keep in sync.
 *
 * NOTHING IS STYLED BY TYPE and no value is reformatted. Leaves go through `JSON.stringify`, so a
 * string keeps its quotes — `"36708.40"` from SQLite and `36708.40` from Postgres read differently
 * because they ARE different, and that difference is what this ORM spends the project declaring.
 */

const ROW = "flex gap-2 py-0.5 font-mono text-xs break-all";
const KEY = "shrink-0 text-ink-600";
const BRANCH = "border-l border-ink-200 pl-3";

function isBranch(value: unknown): value is object {
  return typeof value === "object" && value !== null;
}

function isArray(value: object): value is readonly unknown[] {
  return Array.isArray(value);
}

function childrenOf(value: object): readonly (readonly [string, unknown])[] {
  if (isArray(value)) return value.map((item, index) => [String(index), item] as const);
  return Object.entries(value as Record<string, unknown>);
}

/** What a collapsed branch says about itself: how many, and whether it is a list or an object. */
function brief(value: object, size: number): string {
  return isArray(value) ? `[${String(size)}]` : `{${String(size)}}`;
}

/** `JSON.stringify` returns `undefined` for a few inputs JSON has no spelling for. */
function leaf(value: unknown): string {
  return JSON.stringify(value) ?? String(value);
}

interface JsonNodeProps {
  name: string;
  value: unknown;
  /** Only the root of an entry opens itself; everything under it waits to be asked. */
  defaultOpen?: boolean;
}

export function JsonNode({ name, value, defaultOpen = false }: JsonNodeProps) {
  const children = isBranch(value) ? childrenOf(value) : [];

  // An empty object or array is a fact, not a branch: `<details>` with nothing behind it is a
  // disclosure that discloses nothing.
  if (!isBranch(value) || children.length === 0) {
    return (
      <p className={ROW}>
        <span className={KEY}>{name}</span>
        <span className="text-ink-900">{leaf(value)}</span>
      </p>
    );
  }

  return (
    <details className="py-0.5" open={defaultOpen}>
      <summary className="cursor-pointer font-mono text-xs text-ink-600">
        {name} <span className="text-ink-400">{brief(value, children.length)}</span>
      </summary>
      <div className={BRANCH}>
        {children.map(([key, child]) => (
          <JsonNode key={key} name={key} value={child} />
        ))}
      </div>
    </details>
  );
}
