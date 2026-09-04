"""ONE htmx for both demos, loaded on the ONE page that uses it, and never off a CDN.

THERE IS NO COPY TO KEEP IN STEP, AND THAT IS THE DESIGN. `django-htmx` ships the library inside the
package; Django's `{% htmx_script %}` serves it and Flask serves the SAME file out of the same
installed path. So "do the two demos run the same htmx" is not a thing anybody has to check or
remember — it is the same bytes. The three demos exist to be held side by side, and a difference in
library version between them makes every behavioural difference ask the wrong question first.

WHICH IS WHY A COMMITTED COPY IS WHAT THIS FILE WATCHES FOR. The moment somebody drops an
`htmx.min.js` into `shared/static/`, there are two files and one of them starts going stale — and it
will go stale silently, because both demos keep working. That is the failure this catches while it is
still a diff.

AND WHY A CDN IS WATCHED FOR TOO. The `.gitignore` explains that the built stylesheet is committed so
"the three apps boot with `uv` alone and work offline"; a `<script src="https://unpkg.com/...">`
retracts that quietly — the page still renders with no network and only the paging stops working.

ON ONE PAGE. One page of twenty uses HTMX. In `layout/base.html` the tag would bill nineteen others
for a library they never call, and would be a false statement on each of them. The check is by PAGE,
so a second page adopting HTMX gets written down here instead of the tag creeping back into the shell.

It reads templates as TEXT and boots neither framework, for the reason `routes.py` sets out: a check
that needs a framework to run is a check that gets skipped on the day it matters.
"""

from __future__ import annotations

import pathlib
import re

import pytest

import django_htmx

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEMOS = ("django", "flask")

# The library both demos serve, inside the package that ships it.
_PACKAGE_STATIC = pathlib.Path(django_htmx.__file__).parent / "static" / "django_htmx"
_HTMX_2 = _PACKAGE_STATIC / "htmx-2.min.js"

# A script tag pulling from another host: `https://`, `http://` or the protocol-relative `//`.
_REMOTE_SCRIPT = re.compile(r"""<script[^>]*\ssrc=["'](?:https?:)?//""")

# How each demo asks for htmx. Django has a template tag; Flask names the file it serves. Two
# spellings of one decision, which is what these two demos are.
_HOW_IT_IS_LOADED = {"django": "htmx_script", "flask": "htmx-2.min.js"}

# The one page per demo entitled to load it, and it is the one that uses it.
_HTMX_PAGES = {"lab/pagination/lab_pagination.html"}


def _templates(demo: str) -> dict[str, str]:
    """Every template of a demo as `relative path -> text`."""
    root = _ROOT / demo / "templates"
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in root.rglob("*.html")
    }


def test_the_package_still_ships_the_library_where_both_demos_look_for_it() -> None:
    """`django-htmx` holds htmx 2, minified, at the path both demos serve it from.

    First because it is the assumption everything else rests on: if the package reorganises its
    static directory, Django's tag keeps working and Flask's route 404s, and the useful failure is
    this one rather than a blank pager nobody can explain.
    """
    assert _HTMX_2.exists(), (
        f"{_HTMX_2} is gone: `django-htmx` moved its vendored library, and the Flask demo serves "
        f"that exact path. Follow it there rather than committing a copy."
    )
    source = _HTMX_2.read_text(encoding="utf-8")

    assert "var htmx=" in source, f"{_HTMX_2} does not hold the library"
    assert re.search(r'version:"2\.', source), (
        f"{_HTMX_2} is not htmx 2. The demos run the 2 branch on purpose — 4 is beta — and Django's "
        f"`{{% htmx_script %}}` defaults to 2, so both ends have to say 2 or the two demos diverge."
    )


def test_neither_demo_commits_a_second_copy() -> None:
    """Nobody vendored htmx beside the CSS. Two copies is the drift this arrangement removes."""
    committed = sorted(
        str(path.relative_to(_ROOT))
        for path in _ROOT.rglob("htmx*.js")
        if "node_modules" not in path.parts and ".venv" not in path.parts
    )

    assert committed == [], (
        f"these are copies of htmx inside the repo: {committed}. Both demos serve the one inside "
        f"`django-htmx`; a second file is one that goes stale without either demo breaking."
    )


@pytest.mark.parametrize("demo", _DEMOS)
def test_no_template_pulls_a_script_off_another_host(demo: str) -> None:
    """Nothing is fetched from a CDN. Offline is a property of these demos, not an accident."""
    offenders = sorted(
        path for path, text in _templates(demo).items() if _REMOTE_SCRIPT.search(text)
    )

    assert offenders == [], (
        f"{demo}: these load a script from another host: {offenders}. Serve it from the app "
        f"instead — the demos are meant to boot with `uv` alone and no network."
    )


@pytest.mark.parametrize("demo", _DEMOS)
def test_only_the_page_that_uses_htmx_loads_it(demo: str) -> None:
    """HTMX rides on the page that pages, and on no other. The shell stays free of it."""
    marker = _HOW_IT_IS_LOADED[demo]
    loading = {path for path, text in _templates(demo).items() if marker in text}

    assert loading == _HTMX_PAGES, (
        f"{demo} loads htmx on {sorted(loading)} and the pages entitled to it are "
        f"{sorted(_HTMX_PAGES)}. A page that has adopted HTMX belongs in `_HTMX_PAGES` above; the "
        f"shell (`layout/base.html`) never does, because then nineteen pages pay for one."
    )
