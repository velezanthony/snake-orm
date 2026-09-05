"""Which OPERATIONS each surface of a domain can reach, read from the demos' source.

The companion of `routes.py`, and it exists because comparing SSR against an API by URL is the wrong
join — not slightly wrong, structurally wrong, and the reason is worth writing down once:

    /orders/create          a page has to SHOW a form before it can accept one, so the create
                            operation is TWO routes on the SSR side and one on the API's.
    /orders/delete/<id>     a browser `<form>` can only emit GET and POST, so a deletion is a POST
                            to a path that says "delete", never `DELETE /api/orders/<id>`.
    /api/orders/<id>/lines  an API splits a resource into sub-resources; the page that edits an
                            order edits its lines in the same screen.

Three genuine differences in shape, none of them a difference in what the demo can DO. So the join
is the operation, which is the vocabulary the two surfaces already share and the one the project's
premise is written in: the frameworks hold no logic, they call a use case and render the answer.

TWO HOPS, because the architecture has two. A page WRITES through `usecases.*` and READS through
`viewmodels.*` — the view model is what turns rows into something a template can print — and the
view models call the use cases underneath. Resolving only the direct call would report that the
orders pages perform seven operations when they reach thirteen, and would invent a divergence that
is really a layer.
"""

from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]

# `usecases.result` is the module the `Failure` type comes from, not an operation. It reaches this
# reader because the demos spell it `usecases.result.Failure`, which is an attribute access on the
# same name every operation is called on.
_NOT_AN_OPERATION = frozenset({"result"})


def domains() -> tuple[str, ...]:
    """The demo's domains, taken from the directories rather than from a list kept here."""
    return tuple(
        sorted(
            path.name
            for path in (_ROOT / "fastapi/apps").iterdir()
            if path.is_dir() and not path.name.startswith("__")
        )
    )


def _called_on(relative: str, holder: str) -> set[str]:
    """The attributes called on a name in one file: `usecases.place_order(...)` gives `place_order`.

    A file that does not exist contributes nothing rather than raising: a domain without pages has
    no `views.py`, and that is an answer to this question, not an error.
    """
    path = _ROOT / relative
    if not path.exists():
        return set()
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        target = node.func.value
        if isinstance(target, ast.Name) and target.id == holder:
            found.add(node.func.attr)
    return found - _NOT_AN_OPERATION


def ssr_operations(domain: str) -> set[str]:
    """What the PAGES of a domain can do, across both SSR demos and through their view models.

    The two demos are unioned rather than intersected on purpose: `test_the_demos_serve_the_same_
    routes.py` is what holds Django and Flask to the same pages, so treating them as one surface
    here keeps this file about the SSR-versus-API question instead of re-asking that one.

    WHETHER A DOMAIN HAS PAGES IS ASKED OF THE DEMOS, and it did not used to be. The old reading was
    "a `shared/viewmodels/<domain>_viewmodels.py` exists, so there are pages", which is a PROXY: it
    was needed because a page reads through its view model and calls no use case directly, so
    `direct` comes out empty for a domain that plainly has screens. The proxy held for as long as
    the only reason to write a view model was to draw a page.

    It stopped holding the day `engagement` grew a CSV export. A file is not a page — it is served
    on the API surface here, because this domain has no section of its own — and it needs the same
    shared view model every export has, so that three demos cannot each format an instant their own
    way. Under the old reading, that one module made a domain with zero screens report five
    operations' worth of pages, and the net that watches API-only declarations went red naming a
    decision nobody had reversed.

    So the question is now put to the thing that actually answers it: does either SSR demo have a
    module where pages live. `flask/apps/<domain>/urls.py` is the Flask blueprint of the pages —
    the JSON side is `api.py` — and `django/apps/<domain>/views.py` is Django's, its own JSON side
    being `urls.py`. A domain with neither has no pages, whatever it has in `shared/`.
    """
    page_modules = (f"flask/apps/{domain}/urls.py", f"django/apps/{domain}/views.py")
    if not any((_ROOT / relative).exists() for relative in page_modules):
        return set()
    direct = _called_on(page_modules[0], "usecases") | _called_on(
        page_modules[1], "usecases"
    )
    return direct | _called_on(f"shared/viewmodels/{domain}_viewmodels.py", "usecases")


def api_operations(domain: str) -> set[str]:
    """What the JSON API of a domain can do, across the three demos.

    Unioned for the same reason as above, and with the same division of labour: which of the three
    is missing an endpoint is the other file's question.
    """
    return (
        _called_on(f"fastapi/apps/{domain}/urls.py", "usecases")
        | _called_on(f"flask/apps/{domain}/api.py", "usecases")
        | _called_on(f"django/apps/{domain}/urls.py", "usecases")
    )


def writing_operations(domain: str) -> set[str]:
    """The use cases of a domain that WRITE, derived from whether their body reaches a `commit`.

    Derived and not listed, because the list would be the thing that goes stale: a read that grows a
    write is exactly the change nobody remembers to record, and it is also the change that makes the
    surfaces diverge in the way that matters.

    A `commit` anywhere inside the function counts, including inside a branch that only some inputs
    take: an operation that writes on one path is a write. The reverse —a function that commits
    nothing— is a read however much work it does.
    """
    source = _ROOT / f"shared/usecases/{domain}_usecases.py"
    if not source.exists():
        return set()
    writers: set[str] = set()
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        if any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and inner.func.attr == "commit"
            for inner in ast.walk(node)
        ):
            writers.add(node.name)
    return writers
