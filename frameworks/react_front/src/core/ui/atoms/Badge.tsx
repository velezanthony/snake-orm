import type { ReactNode } from "react";

/** The two badges the stylesheet has: `badge-ok` and `badge-muted`. */
export function Badge({ tone = "muted", children }: { tone?: "ok" | "muted"; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

/**
 * The published/draft pair, spelled once.
 *
 * It appears on the post list, the post detail and the content pages, and a boolean rendered as a
 * badge is exactly the sort of two-line ternary that gets copied with the wrong tone on it.
 */
export function StateBadge({ on, yes, no }: { on: boolean; yes: string; no: string }) {
  return <Badge tone={on ? "ok" : "muted"}>{on ? yes : no}</Badge>;
}
