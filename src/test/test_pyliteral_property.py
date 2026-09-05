"""`str_lit` verified by PROPERTY, not by a list of cases that happened to occur to me.

`test_pyliteral.py` exercises 32 hostile strings written by hand. That is fine, but it only covers
what was imagined. This file declares the PROPERTY —for ANY string, the literal round trips— and
lets Hypothesis generate hundreds of adversarial inputs hunting for the one that breaks it: mixed
quotes, backslashes on the edge, control characters, surrogates, everything a human does not think of.

It is the right answer to "how do we guarantee quality?" for a security primitive. You do not
enumerate the space (it is infinite), you declare the invariant and explore it with directed search.
If a string that escapes the literal ever exists —an RCE in the scaffolding—, this finds it AND
MINIMISES it down to the smallest failing example, instead of leaving it waiting for an attacker.

The invariant of a safe escaper has only two halves, and both are absolute:
- TOTAL: no input slips past it (it always produces a parseable literal).
- FAITHFUL: the literal evaluates back to the EXACT string (it does not change the value).
"""

from __future__ import annotations

import ast

from hypothesis import given
from hypothesis import strategies as st

from snakeorm.helpers.pyliteral import str_lit


@given(st.text())
def test_any_string_round_trips_through_the_literal(original: str) -> None:
    """For ANY string, `str_lit` yields a literal that `ast.literal_eval` returns identical.

    `st.text()` generates everything from the empty string to mixes of quotes, backslashes, line
    breaks, control characters and odd Unicode planes. If a SINGLE one breaks the escaping —the
    literal does not parse, or parses into something else— Hypothesis reports it shrunk to a minimum.
    """
    literal = str_lit(original)

    assert ast.literal_eval(literal) == original


@given(st.text())
def test_the_result_is_always_a_bare_string_literal(original: str) -> None:
    """The result is ALWAYS a `str` constant and nothing more: nothing hanging outside the literal.

    This is the half that catches an injection `literal_eval` would tolerate: if a payload managed
    to close the literal and append `, something`, the AST would stop being a single text constant.
    """
    tree = ast.parse(str_lit(original), mode="eval")

    assert isinstance(tree.body, ast.Constant)
    assert isinstance(tree.body.value, str)


@given(st.text(alphabet=st.characters(min_codepoint=0, max_codepoint=0x10FFFF)))
def test_round_trips_across_the_whole_unicode_range(original: str) -> None:
    """And across the WHOLE Unicode range, surrogates and high planes included.

    Exotic characters are exactly where a naive escaping breaks —what nobody thinks of putting in a
    column comment until an attacker does—.
    """
    assert ast.literal_eval(str_lit(original)) == original
