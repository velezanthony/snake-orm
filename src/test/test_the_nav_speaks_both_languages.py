"""Every title in `mkdocs.yml`'s `nav` has a Spanish translation, and no translation is orphaned.

This is the one hole the four documentation nets leave open, and it is invisible from inside them:
they all read `docs/**`, and this lives in `mkdocs.yml`. A page can have its `.es.md` twin, identical
code blocks and a matching link graph — everything they check — and still appear in the Spanish site
under an English title, because the title is not in the page, it is in the nav.

Nothing said so. `mkdocs build --strict` does not: an untranslated title is not an error, it is a
fallback. So the site builds clean and the reader gets "Working on the demos" in the middle of a
sidebar that is otherwise in Spanish.

Measured when this was written: THREE titles were in that state — `Internals`, `Working on the demos`
and `Coverage history` — all visible in `site/es/index.html`. They had been there long enough that
nobody was going to notice by reading.

It is an EQUALITY between two blocks of the same file, which is what makes it testable rather than a
matter of judgement: the set of titles the nav declares and the set of keys the translation table
answers for. This repository draws that line elsewhere in exactly the same words — an existence and
an equality are checked, a language is not. Nothing here reads the Spanish; it reads whether there
IS one.

The YAML is parsed rather than grepped because a title is `- Key: value` and a value can be a path
or a nested list, and telling those apart with a regex is how a net starts lying about its own
scope.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml

_REPO = pathlib.Path(__file__).resolve().parents[2]
_CONFIG = _REPO / "mkdocs.yml"


class _Loader(yaml.SafeLoader):
    """A loader that survives mkdocs' own tags instead of refusing to read the file.

    `mkdocs.yml` carries `!!python/name:` and `!ENV`-style tags that `SafeLoader` rejects outright.
    They are configuration for plugins and say nothing about the nav, so they are read as `None`
    rather than being a reason to give up and grep.
    """


_Loader.add_multi_constructor(
    "tag:yaml.org,2002:python/name", lambda loader, suffix, node: None
)
_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _config() -> dict[str, Any]:
    """`mkdocs.yml` as data."""
    return yaml.load(_CONFIG.read_text(encoding="utf-8"), Loader=_Loader)


def _nav_titles(nav: list[Any], found: set[str]) -> set[str]:
    """Every title the nav declares, at any depth.

    Recursive because the nav nests —`For users` holds `Guide` holds a page— and a flat read would
    check the sections and miss every page under them, which is most of them.
    """
    for item in nav:
        if not isinstance(item, dict):
            continue
        for title, target in item.items():
            found.add(title)
            if isinstance(target, list):
                _nav_titles(target, found)
    return found


def _translations() -> dict[str, str]:
    """The `es` locale's `nav_translations` table, or `{}` if the plugin stops declaring one."""
    for plugin in _config().get("plugins", []):
        if not isinstance(plugin, dict) or "i18n" not in plugin:
            continue
        for language in plugin["i18n"].get("languages", []):
            if language.get("locale") == "es":
                return dict(language.get("nav_translations") or {})
    return {}


def _titles() -> set[str]:
    """Every title in the nav."""
    return _nav_titles(_config()["nav"], set())


@pytest.mark.parametrize("title", sorted(_titles()))
def test_every_nav_title_has_a_spanish_one(title: str) -> None:
    """Parametrised per TITLE so a failure names the one to translate, not a list to read."""
    assert title in _translations(), (
        f"{title!r} is in `nav` and not in `nav_translations`, so the Spanish site shows it in "
        f"English. Add it under `plugins -> i18n -> languages -> es -> nav_translations` in "
        f"mkdocs.yml."
    )


def test_no_translation_is_left_orphaned() -> None:
    """A translation for a title the nav no longer has is dead weight that reads as coverage.

    The mirror of the test above, and it fails the other way: somebody renames a section, the old
    key stays behind, and the table looks complete while the new title goes untranslated. The
    per-title test would catch the new one — this catches the litter it leaves.
    """
    orphans = sorted(set(_translations()) - _titles())

    assert not orphans, (
        f"{orphans} are translated and no longer appear in `nav`. Remove them: a table with entries "
        f"nobody uses is a table nobody trusts."
    )


def test_the_nav_is_actually_being_read() -> None:
    """The premise. If the parse ever came back empty, every assertion above would pass vacuously.

    That is not hypothetical for this file: it reads YAML through a loader that swallows unknown
    tags, so a structural change to `mkdocs.yml` could leave `nav` as `None` and turn the whole
    file green over nothing.
    """
    titles = _titles()

    assert len(titles) >= 30, (
        f"only {len(titles)} nav titles were parsed out of mkdocs.yml"
    )
    assert "Guide" in titles, (
        "the nav no longer has the section this net was written against"
    )
