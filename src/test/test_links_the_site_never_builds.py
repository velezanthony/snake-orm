"""Every relative link in the documents mkdocs does NOT build points at something that exists.

`mkdocs build --strict` resolves the links of every page it builds, and `make audit` runs it — so
`docs/users/` and `docs/contributors/` are covered. Three places are not: the root `README.md` and
`CONTRIBUTING.md`, which live outside `docs/`, and `docs/features.md`, which `mkdocs.yml` excludes.

Measured both ways: a broken link from `docs/users/` aborts the build; the SAME link from
`docs/features.md` exits 0 and is not even mentioned in the log. Which left the entry points
of the whole graph — the first files anybody opens — as the only ones nobody checked.

And the index is the worst place for that hole. Its whole job is pointing at things: one row per
feature, whose cells link to the code, to the test and to the page that explains it. That shape is
what keeps a claim and its proof one click apart, and it is what stops somebody writing "there is no
connection pool" in a repository that has `drivers/pool.py`. That happened here.

Anchors are checked too, and that half is not decoration: a link to a heading that got renamed lands
the reader at the top of a long page with no error anywhere, which reads as "the section is gone".
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest

from test.docs_scope import ROOT, is_ours

# `[text](target)` where the target is relative. External links (`http…`) and pure anchors (`#x`)
# are somebody else's problem: the first cannot be resolved offline, the second lands on this page.
_LINK = re.compile(r"\[[^\]]*\]\((?!https?://|#)([^)\s]+)\)")


def _unbuilt() -> list[Path]:
    """The markdown the site never builds: the two root files and the feature index.

    `features.md` is in here because it links to SOURCE files, which the built site does not carry —
    so `mkdocs build --strict` can never resolve them and never complains, which is exactly the gap
    this file exists to cover. The plans that used to sit beside it are gitignored now.
    """
    roots = [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "docs" / "features.md",
        ROOT / "docs" / "features.es.md",
    ]
    return [path for path in roots if path.exists() and is_ours(path)]


def _anchor(heading: str) -> str:
    """A heading turned into the id mkdocs gives it: ASCII-folded, lowercase, non-words to dashes.

    The fold is the half that is easy to get wrong, and getting it wrong makes this net lie about
    the Spanish pages. Python-Markdown normalises to NFKD and drops what will not encode to ASCII,
    so `## El catálogo` gives `#el-catalogo`. A word-character slug keeps the accent, computes an
    anchor the site never emits, and then reports every accented heading as broken.
    """
    folded = (
        unicodedata.normalize("NFKD", heading.strip())
        .encode("ascii", "ignore")
        .decode()
    )
    slug = re.sub(r"[^\w\s-]", "", folded.lower())
    return re.sub(r"[\s_]+", "-", slug)


def _anchors_of(path: Path) -> set[str]:
    """Every anchor a markdown file offers: its headings, plus any explicit `id=` it declares."""
    text = path.read_text(encoding="utf-8")
    found = {
        _anchor(line.lstrip("#")) for line in text.splitlines() if line.startswith("#")
    }
    return found | set(re.findall(r'id="([^"]+)"', text))


def _targets() -> list[tuple[str, str, str]]:
    """Every relative link of the unbuilt documents, as (document, raw target, path part)."""
    found: list[tuple[str, str, str]] = []
    for document in _unbuilt():
        name = str(document.relative_to(ROOT))
        for raw in _LINK.findall(document.read_text(encoding="utf-8")):
            found.append((name, raw, raw.split("#", 1)[0]))
    return found


@pytest.mark.parametrize(
    "document, raw, relative", _targets(), ids=lambda value: str(value)
)
def test_every_link_resolves(document: str, raw: str, relative: str) -> None:
    """The file exists, and when the link names an anchor, the anchor exists in it.

    Parametrised per link on purpose: a failure names the exact document AND target to fix, instead
    of handing back a list to diff by eye.
    """
    source = ROOT / document
    target = (source.parent / relative).resolve() if relative else source
    assert target.exists(), f"{document} links to {relative}, which does not exist"

    if "#" not in raw or target.suffix != ".md":
        return
    anchor = raw.split("#", 1)[1]
    assert anchor in _anchors_of(target), (
        f"{document} links to {raw}, but {relative} has no heading giving that anchor"
    )


def test_the_sweep_is_actually_looking_at_something() -> None:
    """The floor: a parametrised net vanishes when its parameter list empties, and this is under it.

    It guards the ACCIDENT — a broken glob, a rename nobody followed — and never the DECISION.
    `EXCLUDED_DIRS` is the one switch, so naming a document here to keep it from being excluded
    would wire a policy underneath the list and quietly contradict it. And it claims no more than
    it checks: that documents were found and links came out of them. Re-deriving `_unbuilt` to
    "verify" it would compare the function to a copy of its own body.
    """
    assert _unbuilt(), (
        "nothing left to sweep: either the glob broke or everything was excluded"
    )
    assert _targets(), "the documents were read but no link came out of them"
