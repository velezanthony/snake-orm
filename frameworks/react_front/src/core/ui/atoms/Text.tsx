import type { ReactNode } from "react";

/** Inline monospace, for an identifier, a path or a snippet of SQL. */
export function Code({ children }: { children: ReactNode }) {
  return <code className="code">{children}</code>;
}

/** The dimmed line the demo uses for a note under something, and for a secondary table cell. */
export function Muted({ className, children }: { className?: string; children: ReactNode }) {
  return <p className={["muted", className].filter(Boolean).join(" ")}>{children}</p>;
}

/** The dashed box a page paints when a query came back with nothing. */
export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
