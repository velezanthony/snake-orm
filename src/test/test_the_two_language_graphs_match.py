"""Two documentation graphs, English and Spanish, with the same shape.

Every `page.md` has a `page.es.md` beside it, and the two point at the same things. That is what
makes the Spanish side a graph you can navigate instead of a pile of pages that dead-ends into
English the moment you follow a link.

These two run over the WHOLE repository, and `EXCLUDED_DIRS` is deliberately empty. So this file is
RED, and the red is the point: it names, one failure per file, every document still waiting for its
twin. A list somebody keeps in their head is a list that gets forgotten; a list the suite reads out
is one that cannot be.

**The red is accepted, and this is the decision, not an oversight.** While the ORM is being built
the English side is the one kept current; documentation parity is work for after. So do not silence
these by deleting them or by widening `EXCLUDED_DIRS` — the debt is meant to be visible until
somebody decides to pay it. The cost of leaving it on is small: the second test compares LINKS, not
prose, so rewording an English paragraph does not break anything. Only adding or dropping a link
does, and mirroring that is a one-line edit.

`test_docs_are_bilingual.py` asks a narrower version of the first question — only the pages mkdocs
publishes, where a missing twin breaks the site rather than the graph. It stays because its failure
means something different: there the twin is required, here it is owed.
"""

from __future__ import annotations

import pathlib
import re
from collections import Counter

import pytest

from test.docs_scope import ROOT, is_bilingual, is_ours

# `[text](target)` where the target is relative: the edges of the graph.
_LINK = re.compile(r"\[[^\]]*\]\((?!https?://|#)([^)\s]+)\)")


def _english_pages() -> list[pathlib.Path]:
    """Every markdown file of ours in its default version (no `.es` suffix)."""
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not path.name.endswith(".es.md") and is_ours(path)
    )


def _twin(page: pathlib.Path) -> pathlib.Path:
    """Where the Spanish version of a page has to live: beside it, `.es.md` for `.md`."""
    return page.with_name(page.name[: -len(".md")] + ".es.md")


def _targets(page: pathlib.Path) -> Counter[str]:
    """What a page points at, counted, with the language suffix folded away.

    Only the path is compared, never the anchor: `#query-dsl` and `#dsl-de-consultas` name the same
    section in two languages, so demanding they match would demand the headings stay untranslated.
    """
    return Counter(
        raw.split("#", 1)[0].replace(".es.md", ".md")
        for raw in _LINK.findall(page.read_text(encoding="utf-8"))
    )


@pytest.mark.parametrize(
    "page",
    [p for p in _english_pages() if is_bilingual(p)],
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_every_page_has_a_spanish_twin(page: pathlib.Path) -> None:
    """`page.md` implies `page.es.md`, one test per page so the failure names the file to write.

    Asked of the documents a reader outside this repository opens, which is what `is_bilingual`
    answers. It used to be asked of every markdown file of ours, and that quietly disagreed with
    `test_docs_are_bilingual` —which had always skipped the plans— so one net owed a translation the
    other exempted. Both were green about their own rule, which is exactly why nobody saw it.
    """
    assert _twin(page).exists(), (
        f"{page.relative_to(ROOT)} has no Spanish version. "
        f"Write {_twin(page).relative_to(ROOT)}, or say why it needs none in `docs_scope`."
    )


@pytest.mark.parametrize(
    "page",
    [p for p in _english_pages() if _twin(p).exists()],
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_the_twin_points_at_the_same_things(page: pathlib.Path) -> None:
    """A page and its translation have the SAME outgoing links, counted.

    This is what keeps the two graphs the same shape. Without it a translation quietly loses a link
    —a paragraph reworded, a "see also" dropped— and the Spanish side degrades one edge at a time,
    with nothing going red, until it is a worse map of the same project.

    Only pages that HAVE a twin are compared; the missing ones are the other test's business.
    """
    english, spanish = _targets(page), _targets(_twin(page))

    missing = english - spanish
    extra = spanish - english
    assert not missing and not extra, (
        f"{page.relative_to(ROOT)} and its translation point at different things.\n"
        f"  only in the English page: {sorted(missing.elements())}\n"
        f"  only in the Spanish page: {sorted(extra.elements())}"
    )


def test_the_pair_of_nets_is_actually_looking_at_something() -> None:
    """The floor: both lists above are parametrised, and a parametrised net empties into silence.

    It checks that the sweep found pages and that the pairing works — nothing more, on purpose. A
    floor that re-derived `_english_pages` to "verify" it would be comparing the function to a copy
    of its own body: green by construction, proving nothing. And naming a document to keep it in
    would wire a policy underneath `EXCLUDED_DIRS`, which is the one switch. The list may shrink
    this to nothing if somebody means it; what it cannot do is shrink by accident and stay quiet.
    """
    pages = _english_pages()

    assert pages, (
        "nothing left to check: either the glob broke or everything was excluded"
    )
    assert any(_twin(p).exists() for p in pages), (
        "no page has a twin: the pairing broke"
    )


def _spanish_pages() -> list[pathlib.Path]:
    """Every markdown file of ours in its Spanish version."""
    return sorted(path for path in ROOT.rglob("*.es.md") if is_ours(path))


def _crossings(page: pathlib.Path, wanted: str) -> list[str]:
    """Links leaving this page for the OTHER language, when they had somewhere to land.

    A page that points at a document with no twin yet is not crossing on purpose — the twin is the
    only thing that would resolve, and demanding it would break the site to make a point. So the
    twin has to EXIST for the link to count as a mistake, which is also what makes this go red on
    its own the day somebody writes it.
    """
    found: list[str] = []
    for raw in _LINK.findall(page.read_text(encoding="utf-8")):
        target = raw.split("#", 1)[0]
        if not target.endswith(".md"):
            continue
        landed = (page.parent / target).resolve()
        if target.endswith(".es.md") == (wanted == "es"):
            continue
        twin = (
            landed.with_name(landed.name[: -len(".md")] + ".es.md")
            if wanted == "es"
            else landed.with_name(landed.name.replace(".es.md", ".md"))
        )
        if twin.exists():
            found.append(target)
    return found


@pytest.mark.parametrize(
    "page", _spanish_pages(), ids=lambda p: str(p.relative_to(ROOT))
)
def test_a_spanish_page_stays_in_the_spanish_graph(page: pathlib.Path) -> None:
    """Two graphs, not one graph read twice: a Spanish page links to Spanish pages.

    `test_the_twin_points_at_the_same_things` folds the suffix away before comparing, so it sees the
    SHAPE of the two graphs and is blind to which one an edge lands in. Under it alone, a Spanish
    page whose every link went to English is indistinguishable from a correct one — same targets,
    same counts, green. That is not a flaw in that test: folding is what lets it compare at all. It
    is a second question, and it needs the second test.

    What it costs a reader is the whole point. Follow one link out of the Spanish guide and the site
    switches language underneath you, and every link from THERE is English too. One edge is enough
    to drop somebody out of their language for the rest of the visit.
    """
    crossings = _crossings(page, wanted="es")

    assert not crossings, (
        f"{page.relative_to(ROOT)} leaves the Spanish graph: {crossings}\n"
        "Each of those has a `.es.md` beside it — point at that one."
    )


@pytest.mark.parametrize(
    "page", _english_pages(), ids=lambda p: str(p.relative_to(ROOT))
)
def test_an_english_page_stays_in_the_english_graph(page: pathlib.Path) -> None:
    """The same rule from the other side, which is the half that is easy to forget.

    Nobody writes `foo.es.md` into an English page on purpose. It arrives by copying a paragraph
    across from the translation, and it survives because the reader who would notice is reading the
    other language.
    """
    crossings = _crossings(page, wanted="en")

    assert not crossings, (
        f"{page.relative_to(ROOT)} leaves the English graph: {crossings}"
    )


def test_both_graphs_have_edges_to_check() -> None:
    """The floor under the pair above: over pages with no links, crossing nothing is free.

    Counted rather than bounded, for the reason `test_limits_are_true` writes down about its own
    floor: a threshold set under the real number swallows the difference without a word.
    """
    spanish = sum(
        len(_LINK.findall(p.read_text(encoding="utf-8"))) for p in _spanish_pages()
    )
    english = sum(
        len(_LINK.findall(p.read_text(encoding="utf-8"))) for p in _english_pages()
    )

    assert spanish and english, (
        f"no edges to check: {spanish} Spanish, {english} English"
    )
