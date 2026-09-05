"""The two SSR demos lay their templates out the SAME way, file for file.

They are two SETS of templates on purpose — a page that names neither Django nor Flask stops being
the one a dev of either recognises as theirs, and these demos exist to be read and copied. What is
NOT on purpose is for the two to drift apart in shape: one calling a page `posts.html` and the other
`post_list.html`, one folding create and update behind a `mode` flag while the other had the delete
confirmation the first one lacked. That had already happened, which is why this exists.

The layout has three slots, and each one answers a different question:

- `<domain>/<action>/<domain>_<action>.html` — a PAGE. The domain is in the name as well as in the
  path, because a grep for `blog_list` should land somewhere, and because a template opened in an
  editor tab says what it is without its folder.
- `<domain>/_<partial>.html` — a PARTIAL of that domain, and the underscore is what says so.
- `layout/<name>.html` — what belongs to NO domain: the shell (`base.html`) and the error page
  (`error.html`). The error page is not called `404.html` because it answers 403 as well.

Two moves earned their place by this rule. `login` and `register` are AUTH, not blog: the URLs said
`/auth/*` all along and the JSON side already had its own app, so the only thing still calling them
blog was the code — a domain that the route and the template agree on and the module does not is a
map with one road drawn wrong. And the error page is not a blog page at all.

It compares NAMES, never contents. The whole reason there are two files is that their contents are
allowed — required — to differ.
"""

from __future__ import annotations

import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEMOS = ("django", "flask")


def _templates(demo: str) -> set[str]:
    """Every template of a demo, as paths relative to its templates directory."""
    root = _ROOT / demo / "templates"
    return {str(path.relative_to(root)) for path in root.rglob("*.html")}


def test_both_demos_have_templates() -> None:
    """There are templates on both sides. Without this the comparison passes vacuously."""
    for demo in _DEMOS:
        assert len(_templates(demo)) >= 10, demo


def test_the_two_demos_lay_their_templates_out_the_same() -> None:
    """Same paths, file for file. The contents differ; the shape does not."""
    django, flask = _templates("django"), _templates("flask")

    assert django == flask, (
        f"only in django: {sorted(django - flask)}; only in flask: {sorted(flask - django)}"
    )


def _follows_the_convention(path: str) -> bool:
    """Whether one template sits in one of the three slots the layout has."""
    parts = path.split("/")
    if len(parts) == 2 and parts[0] == "layout":
        return True  # belongs to no domain: the shell, the error page
    if len(parts) == 2 and parts[1].startswith("_"):
        return True  # a partial of its domain
    if len(parts) == 3:
        domain, action, filename = parts
        return filename == f"{domain}_{action}.html"
    return False


@pytest.mark.parametrize("demo", _DEMOS)
def test_every_template_sits_where_the_convention_says(demo: str) -> None:
    """Checked from the PATH, so a page added tomorrow is covered without anybody remembering.

    A list of the pages there are would have to be edited by whoever adds one, and the person who
    forgets is exactly the person the check was for.
    """
    offenders = sorted(p for p in _templates(demo) if not _follows_the_convention(p))

    assert offenders == [], (
        f"{demo}: these sit in none of the three slots — `<domain>/<action>/<domain>_<action>.html`, "
        f"`<domain>/_<partial>.html` or `layout/<name>.html`: {offenders}"
    )
