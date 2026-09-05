"""The API reference, tied to the public surface it claims to document.

`docs/users/reference/api/` is not written by hand: it is `:::` directives that mkdocstrings resolves
against the package's docstrings on every build. That solves ONE problem — a signature changing while
the page goes on telling the old one — and leaves the other wide open, which is the one that really
ages: exporting a new name and not adding its directive. The page does not lie, it simply does not
mention it, and an incomplete reference reads exactly like a complete one.

Three nets, because these are three different ways of falling behind:

1. Everything the package exports has its directive. This is the one that catches the new undocumented
   symbol.
2. Both languages document EXACTLY the same symbols. The framing prose is translated by hand, so it is
   precisely where a `:::` slips into one page and not the other.
3. Every directive points at something that genuinely exists. `mkdocs build --strict` catches that too,
   but it demands standing the whole site up; here it fails in milliseconds and names the name.
"""

from __future__ import annotations

import importlib
import pathlib
import re
import types

import pytest

import snakeorm

_API = pathlib.Path("docs/users/reference/api")

_DIRECTIVE = re.compile(r"^::: ([\w.]+)", re.M)
"""A mkdocstrings directive: `::: path.to.symbol`, at the start of a line."""


def _pages(language: str) -> list[pathlib.Path]:
    """The reference pages in one language. `es` are the `.es.md` ones; `en` is the rest."""
    is_spanish = language == "es"
    return sorted(
        page for page in _API.glob("*.md") if page.name.endswith(".es.md") is is_spanish
    )


def _documented_paths(language: str) -> set[str]:
    """The full paths (`snakeorm.model.SnakeModel`) that language documents."""
    return {
        path
        for page in _pages(language)
        for path in _DIRECTIVE.findall(page.read_text(encoding="utf-8"))
    }


def _public_surface() -> set[str]:
    """The names the facade re-exports: no leading underscore, and not submodules.

    Same definition as `test_public_api.py`, and for the same reason: `snakeorm/__init__.py` has no
    `__all__` on purpose (it re-exports with a redundant alias, which is what mypy and pyright
    recognise), so the surface is DERIVED at runtime and there is no list of strings to keep in step.
    """
    return {
        name
        for name, value in vars(snakeorm).items()
        if not name.startswith("_") and not isinstance(value, types.ModuleType)
    }


@pytest.mark.parametrize("language", ["en", "es"])
def test_the_reference_pages_were_actually_found(language: str) -> None:
    """The pages exist and carry directives, in EACH language. Without this the rest passes vacuously.

    The classic trap of a test that reads documentation: if the parser stops finding anything, "every
    public name is documented" holds vacuously and the test passes without checking a single symbol.
    """
    paths = _documented_paths(language)

    assert len(_pages(language)) >= 6, f"reference pages are missing in '{language}'"
    assert len(paths) >= 100, f"only {len(paths)} directives were found in '{language}'"


@pytest.mark.parametrize("language", ["en", "es"])
def test_every_public_export_has_a_directive(language: str) -> None:
    """Every name the package exports appears in that language's reference.

    This is the net for the gap mkdocstrings does NOT cover: it generates well what it is asked for,
    and about what nobody asks it says nothing. A public symbol with no directive is a symbol the user
    cannot find.
    """
    documented = {path.rsplit(".", 1)[-1] for path in _documented_paths(language)}

    missing = sorted(_public_surface() - documented)

    assert missing == [], (
        f"exported by `snakeorm` and with no `::: ` in the reference '{language}': {missing}"
    )


def test_both_languages_document_the_same_symbols() -> None:
    """Both references document EXACTLY the same symbols.

    Each page's framing is translated by hand, so adding a directive in one language and forgetting it
    in the other is the natural slip. It leaves the reader of one language with a reference that lies
    by omission, and no per-symbol check sees it.
    """
    english = _documented_paths("en")
    spanish = _documented_paths("es")

    assert english == spanish, (
        f"only in English: {sorted(english - spanish)}; "
        f"only in Spanish: {sorted(spanish - english)}"
    )


@pytest.mark.parametrize("path", sorted(_documented_paths("en")))
def test_every_directive_points_at_something_that_exists(path: str) -> None:
    """Every `::: path` resolves to a real object, by importing the module and looking the attribute up.

    Renaming a symbol without touching the page leaves an orphan directive. `mkdocs build --strict`
    catches it too, but it demands standing the whole site up; this fails in milliseconds and names
    the path.
    """
    module, _, attribute = path.rpartition(".")

    try:
        obj = importlib.import_module(module)
    except ImportError:  # pragma: no cover - only if the path is misspelled
        pytest.fail(
            f"the directive '{path}' points at a module that cannot be imported"
        )

    assert hasattr(obj, attribute), (
        f"the directive '{path}' points at an attribute that does not exist in {module}"
    )
