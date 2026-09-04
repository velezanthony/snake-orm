/**
 * The card, in the four pieces the stylesheet defines: the shell, its head, its body and its foot.
 *
 * Four components rather than one with slots, because that is the shape the SSR templates use and
 * because a card in this demo is genuinely built by composition — some have no head, some have no
 * foot, and the detail pages put a badge in the head next to the title.
 */

import type { ReactNode } from "react";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={["card", className].filter(Boolean).join(" ")}>{children}</section>;
}

/** The same shell as an `<article>`, for a card that IS the page's subject rather than a panel of it. */
export function ArticleCard({ className, children }: { className?: string; children: ReactNode }) {
  return <article className={["card", className].filter(Boolean).join(" ")}>{children}</article>;
}

export function CardHead({
  title,
  sub,
  aside,
  className,
}: {
  title: ReactNode;
  sub?: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <header className={["card-head", className].filter(Boolean).join(" ")}>
      <div>
        <h2 className="card-title">{title}</h2>
        {sub ? <p className="card-sub">{sub}</p> : null}
      </div>
      {aside}
    </header>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={["card-body", className].filter(Boolean).join(" ")}>{children}</div>;
}

export function CardFoot({ children }: { children: ReactNode }) {
  return <footer className="card-foot">{children}</footer>;
}

/**
 * A form that IS the body of a card — `class="card-body form"` on the `<form>` itself, which is the
 * markup the SSR templates use.
 *
 * Worth its own atom because the obvious alternative is wrong in a way nothing complains about:
 * nesting a plain `<form>` inside a `CardBody` leaves the form without `.form`, and `.form` is the
 * `flex flex-col gap-4` that puts space between the fields. The page still renders — with every
 * field jammed against the next.
 */
export function CardForm({
  className,
  onSubmit,
  children,
}: {
  className?: string;
  onSubmit: (form: HTMLFormElement) => void;
  children: ReactNode;
}) {
  return (
    <form
      className={["card-body", "form", className].filter(Boolean).join(" ")}
      onSubmit={(event) => {
        // Every form in this client submits through `fetch`, so the default navigation is never
        // what we want. Preventing it HERE means no page can forget to.
        event.preventDefault();
        onSubmit(event.currentTarget);
      }}
    >
      {children}
    </form>
  );
}
