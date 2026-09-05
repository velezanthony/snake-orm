/**
 * Money, and the two shapes this demo's API sends it in.
 *
 * Billing counts in whole CENTS — an integer, exact, no rounding to argue about — and orders send a
 * `Decimal` serialised as a STRING. Both are correct for what they are, and the mistake would be
 * turning either into a float on the way to the screen: `Number("36708.40") * 100` is not 3670840.
 *
 * So the cents are divided ONCE, here, for display only, and the decimal string is passed through
 * untouched. Nothing in this client ever does arithmetic on a total — the engine already did it.
 */

const FORMAT = new Intl.NumberFormat("en-GB", { style: "currency", currency: "EUR" });

/** An integer number of cents, as money. The division happens here and nowhere else. */
export function fromCents(cents: number): string {
  return FORMAT.format(cents / 100);
}

/**
 * A `Decimal` the API serialised with `str()`.
 *
 * `"None"` is a real value in these payloads: `ordered_total` is `Decimal | None` for a customer who
 * has never ordered, and `str(None)` is the string `"None"`. Rendering that verbatim would put the
 * word None in a money column.
 */
export function fromDecimalString(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "None" || value === "") return "—";
  return value;
}
