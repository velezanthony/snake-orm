/**
 * The demo's button, and the ONE place its classes are spelled.
 *
 * `shared/static/src/app.css` already did the hard half of this: `.btn`, `.btn-primary`, `.btn-md`
 * are components built with `@apply`, precisely so a template says two words instead of fourteen
 * utilities. Writing `className="btn btn-primary btn-md"` in twenty components would throw that
 * away one storey up — the CSS would have one definition of a button and the app would have twenty
 * spellings of it, and the day a third size appears the compiler has nothing to say about the
 * nineteen that did not get it.
 *
 * As a typed prop it is a closed set. `variant="primry"` does not render an unstyled button; it
 * fails to compile.
 */

import { Link, type LinkProps } from "react-router";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

function classes(variant: ButtonVariant, size: ButtonSize, extra?: string): string {
  return ["btn", `btn-${variant}`, `btn-${size}`, extra].filter(Boolean).join(" ");
}

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: ReactNode;
}

export function Button({ variant = "primary", size = "md", className, type = "button", ...rest }: ButtonProps) {
  // `type="button"` by default and not `"submit"`, which is the HTML default and the wrong one:
  // a button inside a form that nobody gave a type to submits it, and that is a bug you find by
  // pressing something unrelated.
  return <button className={classes(variant, size, className)} type={type} {...rest} />;
}

interface ButtonLinkProps extends Omit<LinkProps, "className"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
}

/**
 * A navigation that LOOKS like a button, and is still an anchor.
 *
 * The distinction is not cosmetic: a link can be opened in a new tab, copied, and read out as a
 * destination. A `<button onClick={navigate}>` is none of those things. So "Edit" is this and
 * "Delete" — which performs something — is a `Button`.
 */
export function ButtonLink({ variant = "ghost", size = "md", className, ...rest }: ButtonLinkProps) {
  return <Link className={classes(variant, size, className)} {...rest} />;
}

/** The same, for a URL outside this client — a CSV export, the API, the SSR original. */
export function ButtonAnchor({
  variant = "ghost",
  size = "md",
  className,
  ...rest
}: { variant?: ButtonVariant; size?: ButtonSize; className?: string } & React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <a className={classes(variant, size, className)} {...rest} />;
}
