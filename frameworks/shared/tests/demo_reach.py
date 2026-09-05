"""How far each ORM feature reaches into the demos, computed rather than declared.

The roadmap's *demo* column answers a question the other three cannot: not "is it tested" nor "is it
documented", but **does a user of the demos actually exercise it**. That is a REACHABILITY question
— from a route, through whatever layers, down to the ORM — and it is computed here so the column
cannot drift from the code the way a hand-kept table always does.

WHY REACHABILITY AND NOT "IS IT NAMED IN THIS APP". The three demos SHARE their query layer on
purpose: models and selectors are written once, in `shared/`, and each app re-exports them. From the
outside they look like three independent projects; inside, the queries are one. So asking "does
`fastapi/apps/` contain `.filter(`" measures the architecture and not the feature — it answers `no`
for the very reason the layer is shared, which is the design working.

THE APPROXIMATION, stated rather than discovered: calls are resolved BY NAME and not by import. Two
functions with one name are one node here. That over-approximates — it can only ever say something
is reachable when it is not, never the reverse — and the alternative is a full import resolution for
a signal that is meant to be read by a human.
"""

from __future__ import annotations

import ast
import pathlib
from collections import defaultdict

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SKIPPED = frozenset(
    {"__pycache__", "node_modules", "tests", "migrations", ".mypy_cache"}
)
_HANDLER_FILES = frozenset({"views.py", "api.py", "urls.py"})
"""Where the request handlers live. All three demos put theirs in one of these three."""

DEMOS = ("django", "flask", "fastapi")


def _sources(*roots: str) -> list[pathlib.Path]:
    """Every application source of those roots. Suites and caches are not the application."""
    found: list[pathlib.Path] = []
    for root in roots:
        base = _ROOT / root
        if not base.exists():  # pragma: no cover - a demo could be removed
            continue
        found += [
            path
            for path in sorted(base.rglob("*.py"))
            if not (set(path.relative_to(_ROOT).parts) & _SKIPPED)
            and not path.name.startswith("test_")
        ]
    return found


def _names_in(node: ast.AST) -> set[str]:
    """What this subtree CALLS or reads as an attribute.

    A call on a string literal is dropped, which is the same rule `test_orm_api_coverage` uses and
    for the same reason: `", ".join(...)` is not `SnakeQuery.join`.
    """
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            function = child.func
            if isinstance(function, ast.Attribute):
                if isinstance(function.value, ast.Constant):
                    continue
                found.add(function.attr)
            elif isinstance(function, ast.Name):
                found.add(function.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
            # `PsycopgDriver.connect(...)` NAMES the class, and the attribute alone gives only
            # `connect`. The three synchronous drivers are used on every request through
            # `config.raw_driver`, and the column read `*` — "behind no door" — for a feature every
            # route goes through.
            #
            # Only a CapWords receiver, and that is what keeps it honest rather than a widening:
            # taking every receiver adds locals, and `raw = request.GET.get(...)` followed by
            # `raw.strip()` put `raw()` — an ORM method these demos never call — at `***`. Measured
            # both ways before choosing: the broad rule moved two cells and one of them was a lie.
            receiver = child.value
            if isinstance(receiver, ast.Name) and receiver.id[:1].isupper():
                found.add(receiver.id)
    return found


def _names_outside_functions(tree: ast.Module) -> set[str]:
    """What runs when the module is IMPORTED: its own statements and its class bodies.

    NOT the bodies of its functions, and that line is the whole point. The module door exists
    because starting the application imports the file, so a class body declaring `SnakeColumn` has
    already run before any request arrives — a justification that covers module-level code and stops
    exactly there. A function body has not run; it runs when somebody CALLS it, which the call graph
    already models.

    Sweeping them too made the door reach every name written anywhere in `shared/`, so a selector
    nobody calls read as reachable from all three demos. That turns the `*` tier —"written in the
    domain and behind no door"— into something that can never be reported, and the column into one
    that answers `***` for work that no route touches. Measured while adding five selectors with no
    route: all five came out `***`.
    """
    stripped = ast.Module(body=[], type_ignores=[])
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if isinstance(node, ast.ClassDef):
            # The class body runs on import; the methods inside it do not.
            kept = [
                child
                for child in node.body
                if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            stripped.body.append(
                ast.ClassDef(**{**node.__dict__, "body": kept or [ast.Pass()]})
            )
            continue
        stripped.body.append(node)
    # Bare NAMES too, and only here. `_names_in` reads calls and attributes, which is right for a
    # function body; at module level the load-bearing uses are neither. `SnakeColumn[int]` is a
    # subscript on a name and `SnakeUtc` in an annotation is just a name — the two that made the
    # import sweep necessary in the first place.
    found = _names_in(stripped)
    found |= {
        node.id
        for node in ast.walk(stripped)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return found


def _imported_in(tree: ast.AST) -> set[str]:
    """What this module IMPORTS. Used for the SHARED-domain sweep, not for the module door.

    It was the module door's third source and it over-reached: an import says a file MENTIONS a
    symbol, and the door is supposed to say what RUNS when the application starts. Five selectors
    written in `shared/` and called by nothing came out reachable from all three demos on the
    strength of their import line alone — and with them, `EXPLAIN` was published as `***` while no
    route touched it.

    Reading module-level USE instead keeps every case the imports were added for —`SnakeColumn[int]`
    in a class body, `add_middleware(SnakeDebugASGI)` at module level— because those are names the
    module loads while running. Measured symbol by symbol before the swap: only the two that were
    imported and never called moved.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found |= {alias.asname or alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            found |= {
                (alias.asname or alias.name).split(".")[0] for alias in node.names
            }
    return found


def _dotted_in(tree: ast.AST) -> set[str]:
    """SnakeORM classes named as a dotted STRING, which is how Django registers middleware.

    `settings.MIDDLEWARE` holds `"snakeorm.contrib.django.SnakeDebugMiddleware"` — no import and no
    call, so a reader that only follows names sees nothing and reports the Django demo as shipping
    no debug panel. It does; it just says so in a string.

    Narrow on purpose: only paths that start with `snakeorm.`, and only the last segment. A general
    "any dotted string is a symbol" rule would match half the settings file and quietly turn this
    into a matcher that finds whatever it is asked about.
    """
    return {
        node.value.rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("snakeorm.")
        and "." in node.value
    }


def _graph(*roots: str) -> tuple[dict[str, set[str]], set[str]]:
    """`function -> what it calls`, plus the doors: the handlers a request can enter through."""
    edges: dict[str, set[str]] = defaultdict(set)
    doors: set[str] = set()
    for path in _sources(*roots):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (
            SyntaxError
        ):  # pragma: no cover - a demo that does not parse is another failure
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                edges[node.name] |= _names_in(node)
                if path.name in _HANDLER_FILES:
                    doors.add(node.name)
        # EVERY module's top level is a door, and that is the accurate model rather than a widening:
        # starting the application IMPORTS it, so a class body declaring `SnakeColumn` has already
        # run before any request arrives. Restricting doors to the handler files measured only what
        # is CALLED during a request and reported every declaration as unused — which is how
        # `snake_model` and `SnakeUtc` came out looking absent from demos built on them.
        #
        # It also picks up the wiring Django and Flask keep outside `views/api/urls`: the session
        # hooks in `wire.py` and the middleware in `settings.py` and `app.py`.
        key = f"<module>:{path.relative_to(_ROOT)}"
        edges[key] |= _names_outside_functions(tree) | _dotted_in(tree)
        doors.add(key)
    return edges, doors


def reachable_from_routes(demo: str) -> frozenset[str]:
    """Every name a request to this demo can end up running, `shared/` included."""
    edges, doors = _graph(demo, "shared")
    seen: set[str] = set()
    pending = list(doors)
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        pending += [called for called in edges.get(name, ()) if called not in seen]
    return frozenset(seen)


def named_in_shared() -> frozenset[str]:
    """Every name the shared domain CALLS or imports, whether or not a route ever gets there.

    This is the other half of the `*` tier and it cannot come from `REACH`: a feature written in
    `shared/` that no handler calls is exactly what that tier is for, and asking the reachable set
    about it would always answer no — the same set, asked twice.
    """
    found: set[str] = set()
    for path in _sources("shared"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover
            continue
        found |= _names_in(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                found |= {alias.asname or alias.name for alias in node.names}
    return frozenset(found)


REACH: dict[str, frozenset[str]] = {demo: reachable_from_routes(demo) for demo in DEMOS}
"""What each demo reaches, computed once: the graph does not change between assertions."""

SHARED: frozenset[str] = named_in_shared()
"""What the shared domain names, reachable or not."""
