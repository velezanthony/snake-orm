import type { ReactNode } from "react";

/** The row of buttons a form ends with. A molecule: it only arranges atoms. */
export function FormActions({ children }: { children: ReactNode }) {
  return <div className="flex gap-2 pt-1">{children}</div>;
}
