/**
 * The form atoms: a labelled field, the three controls, and the checkbox.
 *
 * `Field` exists to keep the `htmlFor`/`id` pair from drifting — the one accessibility detail that
 * is invisible when you get it wrong, because the form still looks right and only a screen reader
 * or a click on the label notices. Passing the id once and letting the component wire both ends is
 * the whole reason it is not two lines of JSX at each call site.
 */

import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

export function Field({ id, label, children }: { id: string; label: ReactNode; children: ReactNode }) {
  return (
    <div className="field">
      <label className="label" htmlFor={id}>
        {label}
      </label>
      {children}
    </div>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className="input" {...props} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className="textarea" {...props} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="select" {...props} />;
}

/** The inline `<select>` of the topbar: no label above it, the label is its first disabled option. */
export function InlineSelect(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="select-inline" {...props} />;
}

/** A checkbox with its text beside it, wrapped in the label so the text is part of the hit area. */
export function Check({ children, ...rest }: InputHTMLAttributes<HTMLInputElement> & { children: ReactNode }) {
  return (
    <label className="check">
      <input type="checkbox" {...rest} /> {children}
    </label>
  );
}

