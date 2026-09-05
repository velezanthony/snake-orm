"""Every page of the site exists in BOTH languages. Nothing was watching that.

The documentation is bilingual: English by default (files with no suffix) and Spanish in `X.es.md`.
`mkdocs-static-i18n` with `fallback_to_default` means an untranslated page does NOT break the build —
it shows up in English inside the Spanish site and that is that. That is the right thing for
publishing and it is exactly what makes the drift invisible: you add a page, you forget to translate
it, and the site keeps building without a word.

With two languages maintained by hand, forgetting is not a remote possibility: it is what happens.
And it already happened in this repo — the English type table fell three types behind while the
Spanish one was kept up to date, because the test watching it looked at a single page.

What is NOT checked here is that the translations say the same thing: a test cannot measure that,
and pretending otherwise would hand out false comfort. What is checked is the part that IS
mechanical —that the page exists— which is where 90% of the sloppiness slips in.
"""

from __future__ import annotations

import pathlib

import pytest

from test.docs_scope import OFF_SITE as _OFF_SITE

_DOCS = pathlib.Path("docs")


def _site_pages() -> list[pathlib.Path]:
    """The published pages, in their default version (English, no suffix)."""
    return sorted(
        f
        for f in _DOCS.rglob("*.md")
        if not f.name.endswith(".es.md")
        and not any(part in _OFF_SITE for part in f.parts)
    )


def test_there_are_pages_to_check() -> None:
    """Pages were found. Without this, the rest of the file would pass over an empty list.

    It is the same old trap: if the glob stops matching, "they are all translated" holds vacuously
    and the guard turns into decoration.
    """
    assert len(_site_pages()) >= 20


@pytest.mark.parametrize("page", _site_pages(), ids=lambda p: str(p.relative_to(_DOCS)))
def test_every_published_page_has_its_spanish_version(page: pathlib.Path) -> None:
    """Every published page has its `.es.md`.

    One test per page rather than everything in a single assert: that way the failure names the file
    you have to translate instead of spitting out a list.
    """
    spanish = page.with_suffix("").with_suffix(".es.md")

    assert spanish.exists(), (
        f"{page} has no Spanish version ({spanish.name}). The site would build all the same "
        f"—it falls back to the default language— and the Spanish reader would meet an English "
        f"page without knowing why."
    )


def test_no_spanish_page_is_left_orphaned() -> None:
    """And the other way round: no `.es.md` without its default page.

    An orphan is published in NO language —the i18n starts from the default file—, so it is written
    work that nobody reads. It usually shows up when a page is renamed or deleted and its partner
    is forgotten.
    """
    orphans = [
        f
        for f in _DOCS.rglob("*.es.md")
        if not any(part in _OFF_SITE for part in f.parts)
        and not f.with_suffix("").with_suffix(".md").exists()
    ]

    assert orphans == [], (
        f"Spanish pages with no default-language version: {[str(f) for f in orphans]}. "
        f"The i18n starts from the file with no suffix, so these are published in no language."
    )
