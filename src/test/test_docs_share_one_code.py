"""A page and its translation carry the SAME code. Only the prose has two languages.

The documentation is bilingual and the code is not, and those are different decisions that this
project keeps getting asked to confuse. A reader in Spanish and a reader in English must be able to
copy the same snippet, hit the same output and compare notes; the moment the examples diverge, one
of the two is reading a manual for software that does not exist.

They HAD diverged, quietly and in both ways. Forty-five blocks differed only in their comments,
which is what happens when comments are treated as prose. Seven differed in the CODE itself: a
column called `opening` on one side and `horario` on the other, a variable `when` against `cuando`,
`user.zone` against `user.zona`. Nothing shouted, because each page was internally consistent — the
lie only shows when you put the two side by side, and nothing was putting them side by side.

The eighth was different in kind and worth the paragraph. Both pages quoted the debug report's
summary, and the English one quoted it TWICE with two different answers: `0 duplicadas` on one line
and `0 duplicates` twenty lines later. One of them was the product and the other was a wish. The
product turned out to be the Spanish one, hardcoded in a module with no language switch, so the fix
was in `report.py` and not in either page.

That is the rule this net encodes: a quote of a message is a FACT, not prose. It goes identical in
both languages, because the message that comes out on screen is one.

WHAT THIS FILE DOES NOT DO, and the distinction is the whole point. It compares two artefacts for
equality. It does not judge what LANGUAGE they agree in, because that judgement cannot be made
mechanically: three nets in this repository once tried, by listing Spanish markers and flagging what
matched, and a list of markers only ever finds the markers it already knows. They were named for a
guarantee —"the strings are English"— that their bodies never gave, and Spanish lived under them in
the green. A test that cannot deliver its own name is worse than no test, because it manufactures
confidence. Equality can be checked; language cannot, so only equality is claimed here.

The pairing itself — that every page HAS a translation — belongs to `test_docs_are_bilingual`, which
is the same kind of check as this one: mechanical, and honest about its limit.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_DOCS = pathlib.Path("docs")
_FENCE = re.compile(r"^```")


def _blocks(path: pathlib.Path) -> list[str]:
    """The fenced code blocks of a page, in order and without their fences."""
    blocks: list[str] = []
    inside = False
    buffer: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line.strip()):
            if inside:
                blocks.append("\n".join(buffer))
                buffer = []
            inside = not inside
        elif inside:
            buffer.append(line)
    return blocks


def _pairs() -> list[tuple[pathlib.Path, pathlib.Path]]:
    """Every page that HAS a translation, beside it.

    A page without one is not this file's business: it falls out of the pairing and
    `test_docs_are_bilingual` is the one that turns it red.
    """
    return sorted(
        (page, spanish)
        for page in _DOCS.rglob("*.md")
        if not page.name.endswith(".es.md")
        and (spanish := page.with_name(page.name[:-3] + ".es.md")).exists()
    )


def test_there_are_pairs_to_check() -> None:
    """There are translated pages to compare. Without this the check below passes vacuously.

    Non-empty rather than a floor of twenty. A floor guards against the same emptiness and costs a
    number that nobody updates: it survives its own reason for existing, drifts away from the
    documentation it was measuring, and the day it is finally wrong it is wrong about nothing in
    particular. How MANY pages are translated is `test_docs_are_bilingual`'s question, and it asks it
    one page at a time.
    """
    assert _pairs(), "no page has a translation, so the comparison below checks nothing"


@pytest.mark.parametrize("page,spanish", _pairs(), ids=lambda p: p.name)
def test_both_languages_carry_the_same_code(
    page: pathlib.Path, spanish: pathlib.Path
) -> None:
    """The two versions of this page have the same code blocks, in the same order.

    Comments count as code here, and that is the point: they live INSIDE the example, so a reader
    copying the block gets them too. Prose explains the example from outside it; a comment is part of
    what runs.
    """
    ours, theirs = _blocks(page), _blocks(spanish)

    assert len(ours) == len(theirs), (
        f"{page.name} has {len(ours)} code blocks and its translation {len(theirs)}"
    )
    differing = [index for index, (a, b) in enumerate(zip(ours, theirs)) if a != b]
    assert differing == [], (
        f"{page.name}: blocks {differing} differ between languages. The prose has two languages, "
        f"the code has one."
    )
