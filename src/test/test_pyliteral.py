"""`str_lit` is a SECURITY primitive: it writes a string as a Python literal that cannot be broken.

The migration renderer and the DB-first scaffolding both use it, and both generate `.py` code that
another process imports. With external data —table names and comments coming from the database—, a
badly escaped literal is code execution at import time. An RCE from exactly that was confirmed
before the escaping was centralised here.

This test exercises the primitive DIRECTLY, not through its two consumers. The coverage via
`render_models` exists, but if somebody refactors that generator, the edge cases go with it. A
security primitive deserves its own net: the property is simple and absolute —whatever goes in, a
valid Python literal comes out that evaluates back to the original string— and it is checked by
generating hostile inputs and round-tripping them through `ast.literal_eval`.
"""

from __future__ import annotations

import ast

import pytest

from snakeorm.helpers.pyliteral import str_lit

# Each one tries to break the literal in a different way. If `str_lit` failed on any of them, the
# `ast.literal_eval` of the result would not rebuild the original (or would not even parse).
_HOSTILE = [
    "",
    "normal",
    'with "double quotes"',
    "with 'single quotes'",
    "\"both\" at 'once'",
    "back\\slash",
    "slash at the end\\",
    'escaped \\" quote inside',
    "line\nbreak\nhere",
    "carriage\rreturn\rhere",
    "tab\tinside",
    'triple"""quote',
    "control\x00\x01\x1f\x7f",
    "closes the literal\") + __import__('os').system('rm -rf /') + (\"",
    "unicode: café — 日本語 — 🐍",
    "\\n literal (backslash-n, no salto)",
]


@pytest.mark.parametrize("original", _HOSTILE, ids=lambda v: repr(v)[:32])
def test_the_literal_round_trips_back_to_the_original(original: str) -> None:
    """Whatever `original` is, `str_lit` yields a literal that `ast.literal_eval` returns UNCHANGED.

    That is the whole property of a safe escaper: total (no input slips past it) and faithful (it
    does not change the value). An escaping that almost works produces a literal that almost round
    trips, and "almost" is where injection lives.
    """
    literal = str_lit(original)

    rebuilt = ast.literal_eval(literal)

    assert rebuilt == original


@pytest.mark.parametrize("original", _HOSTILE, ids=lambda v: repr(v)[:32])
def test_the_result_is_a_single_string_literal_and_nothing_more(original: str) -> None:
    """What comes out is ONE string literal, not an expression with anything hanging off it.

    `ast.literal_eval` also accepts tuples or numbers; here the AST is required to be exactly a
    constant of type `str`. That way a payload that managed to close the literal and append
    `, __import__` is caught as 'this is no longer just a string', even if `literal_eval` did not
    blow up.
    """
    tree = ast.parse(str_lit(original), mode="eval")

    assert isinstance(tree.body, ast.Constant)
    assert isinstance(tree.body.value, str)
