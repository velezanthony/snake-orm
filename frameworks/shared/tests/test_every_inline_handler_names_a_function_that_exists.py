"""Every `onclick="snakeX(this)"` in either demo names a function `demo.js` actually defines.

THE JOINT NOBODY WAS WATCHING. `frameworks/shared/static/demo.js` is one file served by two demos,
and the templates reach into it by NAME, in a string, inside an attribute. Rename the function and
both demos keep rendering, keep passing every route walk, and the control silently stops working —
the browser throws `snakeRefreshWarehouses is not defined` into a console nobody has open. There is
no import to break and no template to fail: a string stopped matching a string.

It is the same class of thing `test_no_two_routes_claim_one_url_name.py` was written for, and it
looks the same from every other net: the markup is well formed, the page answers 200, the templates
mirror each other file for file. The damage is inside one attribute of one tag.

Read as TEXT, both sides. Executing the JavaScript would mean a runtime this suite does not have,
and the question — "is this name defined over there" — does not need one.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEMO_JS = _ROOT / "shared" / "static" / "demo.js"
_DEMOS = ("django", "flask")

# `function snakeNav(select) {` — the only way this file declares one, and deliberately so: a
# `const snakeNav = ...` would not be hoisted, and an inline handler can fire before it is assigned.
_DECLARED = re.compile(r"^(?:async )?function (\w+)\(", re.MULTILINE)

# `onclick="snakeRefreshWarehouses(this)"`, `onchange="snakeNav(this)"`: any inline handler calling
# something by name. The call has to be the whole attribute, which is what these demos do.
_CALLED = re.compile(r"""\son[a-z]+=["'](\w+)\(""")


def _templates(demo: str) -> dict[str, str]:
    """Every template of a demo as `relative path -> text`."""
    root = _ROOT / demo / "templates"
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in root.rglob("*.html")
    }


def test_the_reader_found_functions_and_handlers() -> None:
    """Both halves matched something. Otherwise the comparison below passes over two empty sets.

    This file's failure mode is silence: change how `demo.js` declares its functions, or how a
    template spells a handler, and the check keeps reporting success over nothing at all.
    """
    declared = set(_DECLARED.findall(_DEMO_JS.read_text(encoding="utf-8")))
    called = {
        name
        for demo in _DEMOS
        for text in _templates(demo).values()
        for name in _CALLED.findall(text)
    }

    assert declared, (
        f"no `function name(` found in {_DEMO_JS}: the reader stopped matching"
    )
    assert called, "no inline handler found in either demo: the reader stopped matching"


@pytest.mark.parametrize("demo", _DEMOS)
def test_every_handler_a_template_calls_is_defined(demo: str) -> None:
    """A handler naming a function that is not there is a dead control and a console nobody reads."""
    declared = set(_DECLARED.findall(_DEMO_JS.read_text(encoding="utf-8")))
    missing = sorted(
        {
            f"{path}: {name}"
            for path, text in _templates(demo).items()
            for name in _CALLED.findall(text)
            if name not in declared
        }
    )

    assert missing == [], (
        f"{demo} calls handlers `shared/static/demo.js` does not define: {missing}. Both demos serve "
        f"that one file, so the name in the attribute and the name in the function have to agree."
    )
