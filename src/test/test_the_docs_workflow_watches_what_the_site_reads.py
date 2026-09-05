"""The docs workflow rebuilds when anything the SITE reads changes, not only when `docs/` does.

`.github/workflows/docs.yml` filters by `paths`, which is the right call: a rule that cannot be
forgotten beats one somebody has to remember. But the filter has to name every root the published
site actually reads, and the API reference reads a second one — `mkdocstrings` is configured with
`paths: [src]`, and the pages under `docs/users/reference/api/` are almost nothing but `:::`
directives resolved out of the package's own docstrings.

So a commit that only rewrites docstrings changes what the site SHOWS and touches no file the filter
watches. The workflow does not fail: **it does not run**, and the site keeps serving the old text
until somebody edits `docs/` for an unrelated reason. That is the worst shape a CI gap takes, because
there is no red anywhere to notice.

This was found by a session working on another repository, which hit the same defect through
`pymdownx.snippets` — a stub under `docs/` embedding a file from the root. Different mechanism, same
question: does the filter name every root the site reads?
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

_REPO = pathlib.Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO / ".github" / "workflows" / "docs.yml"
_MKDOCS = _REPO / "mkdocs.yml"
_API = _REPO / "docs" / "users" / "reference" / "api"


class _Loader(yaml.SafeLoader):
    """A loader that survives the tags mkdocs and Actions carry instead of refusing the file."""


_Loader.add_multi_constructor(
    "tag:yaml.org,2002:python/name", lambda loader, suffix, node: None
)
_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _watched_paths() -> list[str]:
    """The `paths` filter of the publish workflow's push trigger."""
    config = yaml.load(_WORKFLOW.read_text(encoding="utf-8"), Loader=_Loader)
    # `on:` is parsed as the boolean True by YAML 1.1, which is the trap in every Actions file.
    triggers = config.get("on", config.get(True, {}))
    if not isinstance(triggers, dict):  # pragma: no cover - the shape changed under us
        return []
    # An empty list and not a `KeyError`, so the sentinel below gets to say what happened. A guard
    # that dies with a raw traceback tells the reader the test is broken, not the workflow.
    return list(triggers.get("push", {}).get("paths", []))


def _mkdocstrings_roots() -> list[str]:
    """The directories `mkdocstrings` is told to import from."""
    config = yaml.load(_MKDOCS.read_text(encoding="utf-8"), Loader=_Loader)
    for plugin in config.get("plugins", []):
        if isinstance(plugin, dict) and "mkdocstrings" in plugin:
            handlers = plugin["mkdocstrings"].get("handlers", {})
            return list(handlers.get("python", {}).get("paths", []))
    return []


def test_the_filter_is_actually_being_read() -> None:
    """The sentinel. Without it, a broken parse would compare empty lists and pass in green.

    Both assertions below are "every X is in Y". If `_watched_paths` ever came back empty because
    the YAML shape changed —`on:` is famously parsed as the boolean `True`— the first would still
    hold vacuously and the second would hold over nothing. This is what refuses to be vacuous.
    """
    watched = _watched_paths()

    assert len(watched) >= 3, f"only {watched} was parsed out of the workflow"
    assert "docs/**" in watched, "the filter no longer watches the documentation itself"


def test_mkdocstrings_still_reads_the_package() -> None:
    """The premise for the test below: the site really does render from `src/`.

    If the API reference ever stopped being generated —hand-written pages, say— the requirement
    would go away and demanding it would be enforcing a rule nobody owes.
    """
    roots = _mkdocstrings_roots()

    assert roots, "mkdocstrings declares no import path"
    assert "src" in roots, f"mkdocstrings now reads {roots}, not `src`"
    directives = sum(
        len(re.findall(r"^::: ", page.read_text(encoding="utf-8"), re.MULTILINE))
        for page in _API.glob("*.md")
    )
    assert directives >= 100, (
        f"only {directives} `:::` directives are left in the API reference"
    )


@pytest.mark.parametrize("root", ["src/**"])
def test_every_root_the_site_reads_is_watched(root: str) -> None:
    """A root the site renders from has to trigger the publish, or the site goes stale silently.

    `src/**` is here because the API reference is `mkdocstrings` directives resolved against the
    package's docstrings. Rewrite a docstring and the published page changes; leave `src` out of the
    filter and the workflow never starts, so the change is live in the repository and absent from
    the site, with nothing red anywhere.
    """
    assert root in _watched_paths(), (
        f"{root} is not in the workflow's `paths`, and the site renders from it. A commit that only "
        f"touches it changes the published documentation and the workflow does not run — it does "
        f"not fail, it does not start."
    )
