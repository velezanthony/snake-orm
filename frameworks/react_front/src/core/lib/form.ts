/**
 * Reading a field out of a submitted form, honestly.
 *
 * `FormData.get()` answers `string | File | null`, and this client had been doing
 * `String(data.get("title") ?? "")` in a dozen places. On a text input that is right; on a file input
 * it stringifies to the literal text `[object File]` and posts it as if it were what the person
 * typed. The type said so all along and nothing was reading the type — the linter is what pointed
 * at it, twelve times.
 *
 * So a `File` is NOT a string here and does not pretend to be: it reads as empty, which is what an
 * unfilled text field reads as, and is the honest answer to "what did they type in this box".
 */

/** The text of a field, trimmed. A missing field and a file both read as empty. */
export function text(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === "string" ? value.trim() : "";
}

/** The text of a field, NOT trimmed — for a password, where a space is a character. */
export function secret(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === "string" ? value : "";
}

/** A field as a number. `NaN` for anything unparseable, which the caller must handle. */
export function number(form: FormData, name: string): number {
  return Number(text(form, name));
}

/**
 * A checkbox. An unchecked box sends NOTHING — it is absent from the FormData, not present as
 * "false" — which is the one thing about HTML forms that surprises everybody once.
 */
export function flag(form: FormData, name: string): boolean {
  return form.get(name) !== null;
}
