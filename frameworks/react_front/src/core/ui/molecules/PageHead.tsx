import type { ReactNode } from "react";

/** The heading block every page in the three demos opens with: an `h1` and one line under it. */
export function PageHead({ title, lede, actions }: { title: string; lede?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="h1">{title}</h1>
        {actions ? <div className="ml-auto flex flex-wrap gap-2">{actions}</div> : null}
      </div>
      {lede ? <p className="lede">{lede}</p> : null}
    </div>
  );
}
