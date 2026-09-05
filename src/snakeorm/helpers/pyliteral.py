"""Writing a string as a SAFE Python literal. One single place, two consumers (the migration
renderer and the DB-first scaffolding), both generating `.py` that another process imports.

A badly escaped string breaks the literal and whatever follows runs on import; in the scaffolding
that is RCE, because the table/column names and comments come from the database.
"""

from __future__ import annotations

_ESCAPES: dict[str, str] = {
    "\\": "\\\\",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}
"""Characters with a FIXED escape. The quote is not here because it depends on which one is used."""


def _encode(value: str, quote: str) -> str:
    """Escapes `value` as a string literal for the given quote (the way CPython/ruff do).

    It escapes the quote, the control range and SURROGATES; everything else passes through. A lone
    surrogate (`\\ud800`) is a valid `str` but is not encodable to UTF-8, so it is emitted as
    `\\uXXXX` to make the escaper total over ANY `str` and keep the file writable.
    """
    out: list[str] = []
    for char in value:
        code = ord(char)
        escaped = _ESCAPES.get(char)
        if escaped is not None:
            out.append(escaped)
        elif char == quote:
            out.append("\\" + quote)
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\x{code:02x}")
        elif 0xD800 <= code <= 0xDFFF:
            # Lone surrogate: `\uXXXX`, the only way to fit it into an encodable literal.
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    return f"{quote}{''.join(out)}{quote}"


def str_lit(value: str) -> str:
    """A string as a valid Python literal, double quotes unless single ones save escapes.

    That is `ruff format`'s rule (the generated file passes `ruff check`); it ALWAYS returns a
    closed, correct literal, whatever the content of `value`.
    """
    double = _encode(value, '"')
    single = _encode(value, "'")
    return single if single.count("\\") < double.count("\\") else double
