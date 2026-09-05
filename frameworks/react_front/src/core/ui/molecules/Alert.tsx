import type { ReactNode } from "react";

/**
 * The demo's two banners, `alert-ok` and `alert-error`, exactly as the SSR templates spell them.
 *
 * `role="alert"` only on the error: an assistive reader should be interrupted by a failure and
 * should not be interrupted by "saved".
 */
export function Alert({ kind, children }: { kind: "ok" | "error"; children: ReactNode }) {
  return (
    <p className={`alert alert-${kind} mb-4`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </p>
  );
}
