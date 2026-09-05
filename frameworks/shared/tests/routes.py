"""The routes each demo serves, READ FROM ITS SOURCE and never by booting it.

`ast` and not an import, for the reason `test_nav_is_wired_in_both_demos.py` sets out at length and
which applies here word for word: importing means starting Django's settings and Flask's app from
inside a suite whose whole premise is an in-memory SQLite and no server, and **a check that needs a
framework to run is a check that gets skipped on the day it matters**.

The three demos declare their routes in three shapes, and all three are regular enough to read:

    Django    `config/urls.py` mounts `path("<prefix>", include("apps.X.Y"))`, and the included
              module holds `urlpatterns = [path("<route>", view, name=...), ...]`. The served path
              is the concatenation, which is why the prefix cannot be skipped: `apps/auth/urls.py`
              and `apps/auth/web_urls.py` hold DIFFERENT surfaces of one domain.
    Flask     a `Blueprint(name, __name__, url_prefix="/x")` plus `@name.get("/y")` decorators. Only
              the blueprints `app.py` actually registers count — one that is written and never
              mounted serves nothing, and counting it would let a demo look complete because a file
              exists.
    FastAPI   an `APIRouter(prefix="/api/x")` plus `@router.get("/y")`, mounted by `include_router`.

WHY THE MOUNT IS PARSED TOO, in the two frameworks that have one. `main.py` and `app.py` import the
router under an ALIAS (`from apps.orders.urls import orders as orders_bp`) and mount the alias, so
the join between "this file declares routes" and "the application answers them" is the pair of
statements — and a router written, imported and never mounted is exactly the kind of thing that
looks finished in a diff.

TWO READINGS OF THE SAME WALK, and the second one is why this module stopped being three functions
that answer `set[str]`. `routes(demo)` yields a `Route` that carries WHERE THE HANDLER IS —
`(module, handler)`— alongside the path, and `handler_of()` hands back the function's syntax tree.
A net that only compares paths can say the three demos serve `/api/posts`; it cannot say what comes
back out of it, and `test_the_three_apis_answer_the_same_shape.py` needs the body to do that. The
path-only functions below are kept and are now derived from the same walk, so there is ONE reader
and not two that can drift apart while both stay green.

A `Route` whose `module` is `None` is one this reader could not resolve to a function it can read —
today that is Django's two class-based `as_view()` mounts, drf-spectacular's schema and its Swagger
UI, which are the framework's own plumbing and belong to no domain. Saying so with `None` is what
keeps the path-only reading complete while the handler-aware one stays honest about what it opened.
"""

from __future__ import annotations

import ast
import functools
import pathlib
import re
from dataclasses import dataclass

_ROOT = pathlib.Path(__file__).resolve().parents[2]

# The three demos, and how each one says "this router is mounted". The tuple is the argument order
# `routes()` dispatches on, kept here so the list of demos is written once.
DEMOS = ("django", "flask", "fastapi")

# What a path PARAMETER is called stops mattering the moment two frameworks are compared: Django
# writes `<int:order_id>`, Flask the same, FastAPI `{order_id}`. They are the same route with three
# spellings, so all three collapse to one token. The NAME is deliberately dropped as well — calling
# it `order_id` on one demo and `pk` on the other is a difference in vocabulary, not in surface.
_PARAMETER = re.compile(r"<[^>]+>|\{[^}]+\}")


@dataclass(frozen=True)
class Route:
    """One route of one demo: the path served, and the function that answers it.

    `module` and `handler` are `None` together when the route is answered by something this reader
    does not resolve to a `def` it can read — a class-based view mounted with `as_view()`. The path
    is still reported, because a path-only comparison has no business losing a route just because
    the body behind it is out of reach.
    """

    demo: str
    path: str
    module: str | None
    handler: str | None

    @property
    def is_api(self) -> bool:
        """Whether the APPLICATION serves this under `/api`, decided by the path and nothing else."""
        return self.path == "/api" or self.path.startswith("/api/")

    @property
    def where(self) -> str:
        """How this route is named in a message: stable under a change of URL."""
        return f"{self.demo} {self.module}.{self.handler}"


def normalise(path: str) -> str:
    """One spelling for one route: parameters collapsed, no trailing slash.

    Django keeps its trailing slash ON PURPOSE — `APPEND_SLASH` is the framework's convention and
    fighting it would make the demo un-Django-like to read — so the slash is not a difference worth
    reporting. What IS worth reporting is a page one demo serves and the other does not.
    """
    return "/" + _PARAMETER.sub("<var>", path).strip("/")


def _literal(node: ast.expr | None) -> str | None:
    """The string a node is, or None if it is anything else. Nothing here evaluates code."""
    return (
        node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        else None
    )


def _keyword(call: ast.Call, name: str) -> str | None:
    """A keyword argument of a call, as a string literal."""
    for keyword in call.keywords:
        if keyword.arg == name:
            return _literal(keyword.value)
    return None


def _tree(relative: str) -> ast.Module:
    """The parsed source of one file of one demo."""
    return _parse(_ROOT / relative)


def _source(path: pathlib.Path) -> str:
    """The text of one file. The single door every parse goes through, on purpose.

    One door and not `read_text` scattered through the walkers, because that is what lets a check of
    THIS reader feed it a mutated source without writing to the repository — which is how the two
    shape divergences `test_the_three_apis_answer_the_same_shape.py` was built for get proved to
    turn it red, on a working tree that stays clean.
    """
    return path.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=None)
def _parse(path: pathlib.Path) -> ast.Module:
    """One parse per file: some of them are visited many times over one run."""
    return ast.parse(_source(path))


def _module_file(demo: str, dotted: str) -> pathlib.Path | None:
    """The file a dotted module name refers to, or None if it is not one of this demo's own.

    `apps.*` is the demo's package and resolves under that demo; `shared.*` is the one domain layer
    all three share. Anything else — a framework, the standard library — is not something this
    reader follows, and saying so by returning None keeps it from guessing.
    """
    if dotted.startswith("apps."):
        candidate = _ROOT / demo / (dotted.replace(".", "/") + ".py")
    elif dotted.startswith("shared."):
        candidate = _ROOT / (dotted.replace(".", "/") + ".py")
    else:
        return None
    return candidate if candidate.exists() else None


@functools.lru_cache(maxsize=None)
def _module_bindings(demo: str, dotted: str) -> dict[str, str]:
    """The names in a module that ARE modules, mapped to what they name.

    Told apart from a value by asking the filesystem whether the file exists, not by how the name is
    capitalised: `from apps.orders import api` binds `api` to `apps.orders.api` because
    `apps/orders/api.py` is there, while `from apps.orders.api import place` binds a function.
    Django's urlconf names its views through the first form, which is the one this reader needs.
    """
    path = _module_file(demo, dotted)
    if path is None:
        return {}
    found: dict[str, str] = {}
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                submodule = f"{node.module}.{alias.name}"
                if _module_file(demo, submodule) is not None:
                    found[alias.asname or alias.name] = submodule
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found[alias.asname or alias.name] = alias.name
    return found


# --- Django ------------------------------------------------------------------------------------


def _django_mounts() -> list[tuple[str, str]]:
    """`(prefix, module)` for every `path(..., include("apps.X.Y"))` of the root urlconf."""
    mounts: list[tuple[str, str]] = []
    for node in ast.walk(_tree("django/config/urls.py")):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "path"):
            continue
        if len(node.args) != 2 or not isinstance(node.args[1], ast.Call):
            continue
        included = node.args[1]
        if getattr(included.func, "id", "") != "include" or not included.args:
            continue
        prefix, module = _literal(node.args[0]), _literal(included.args[0])
        if prefix is not None and module is not None:
            mounts.append((prefix, module))
    return mounts


def _django_handler(bindings: dict[str, str], call: ast.Call) -> tuple[str, str] | None:
    """`(module, function)` for the view a `path()` names, or None when it is not a plain function.

    `path("orders/", views.list_orders)` resolves; `path("schema/", SpectacularAPIView.as_view())`
    does not, and returning None rather than a guess is what makes the `None` in `Route` mean
    something.
    """
    if len(call.args) < 2:
        return None
    handler = call.args[1]
    if not (isinstance(handler, ast.Attribute) and isinstance(handler.value, ast.Name)):
        return None
    module = bindings.get(handler.value.id)
    return None if module is None else (module, handler.attr)


def _django_routes() -> list[Route]:
    """Every route the Django demo serves, prefix included, handler resolved where it can be."""
    routes: list[Route] = []
    for prefix, module in _django_mounts():
        source = _module_file("django", module)
        if source is None:
            continue
        bindings = _module_bindings("django", module)
        for node in ast.walk(_parse(source)):
            if not (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", "") in {"path", "re_path"}
                and node.args
            ):
                continue
            route = _literal(node.args[0])
            if route is None:
                continue
            found = _django_handler(bindings, node)
            routes.append(
                Route(
                    "django",
                    normalise(prefix + route),
                    found[0] if found else None,
                    found[1] if found else None,
                )
            )
    return routes


# --- Flask and FastAPI: a decorated function on a prefixed object --------------------------------

_METHODS = frozenset({"get", "post", "put", "patch", "delete", "route"})


def _mounted_objects(entry: str, mounter: str) -> set[tuple[str, str]]:
    """`(module, name)` for every router this demo's entry point actually MOUNTS.

    Two statements have to meet: the import that renames it and the call that mounts it. A router
    imported and never mounted answers nothing, and one mounted without being imported does not
    parse — so this is the join, read rather than assumed.
    """
    tree = _tree(entry)
    aliases: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("apps."):
            for alias in node.names:
                aliases[alias.asname or alias.name] = (node.module or "", alias.name)
    mounted: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call) and getattr(node.func, "attr", "") == mounter
        ):
            continue
        for argument in node.args:
            if isinstance(argument, ast.Name) and argument.id in aliases:
                mounted.add(aliases[argument.id])
    return mounted


def _own_prefix(tree: ast.Module, name: str, factory: str, prefix_arg: str) -> str:
    """The prefix the blueprint or router gives itself, from the call that builds it."""
    prefix = ""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not (isinstance(target, ast.Name) and target.id == name):
            continue
        if (
            isinstance(node.value, ast.Call)
            and getattr(node.value.func, "id", "") == factory
        ):
            prefix = _keyword(node.value, prefix_arg) or ""
    return prefix


def _decorated_routes(
    demo: str, entry: str, mounter: str, factory: str, prefix_arg: str
) -> list[Route]:
    """Flask's and FastAPI's: a decorated function on an object the entry point mounts."""
    routes: list[Route] = []
    for module, name in sorted(_mounted_objects(entry, mounter)):
        source = _module_file(demo, module)
        if source is None:
            continue
        tree = _parse(source)
        prefix = _own_prefix(tree, name, factory, prefix_arg)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                attribute = decorator.func
                if (
                    not isinstance(attribute, ast.Attribute)
                    or attribute.attr not in _METHODS
                ):
                    continue
                if getattr(attribute.value, "id", "") != name:
                    continue
                route = _literal(decorator.args[0]) if decorator.args else None
                if route is not None:
                    routes.append(
                        Route(demo, normalise(prefix + route), module, node.name)
                    )
    return routes


# --- the two readings ----------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def routes(demo: str) -> tuple[Route, ...]:
    """Every route one demo serves, with the handler behind it where this reader can name one."""
    if demo == "django":
        return tuple(_django_routes())
    if demo == "flask":
        return tuple(
            _decorated_routes(
                "flask", "flask/app.py", "register_blueprint", "Blueprint", "url_prefix"
            )
        )
    if demo == "fastapi":
        return tuple(
            _decorated_routes(
                "fastapi", "fastapi/main.py", "include_router", "APIRouter", "prefix"
            )
        )
    raise ValueError(f"unknown demo {demo!r}; the three are {DEMOS}")


def handler_of(route: Route) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The syntax tree of the function that answers a route, or None if there is no reading it.

    Top level only, which is not a limitation but the rule: a decorator that mounts a route runs at
    import time on a module-level object, so a handler nested inside another function is not one
    this application ever serves.
    """
    if route.module is None or route.handler is None:
        return None
    path = _module_file(route.demo, route.module)
    if path is None:
        return None
    for node in _parse(path).body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == route.handler
        ):
            return node
    return None


def django_routes() -> set[str]:
    """Every path the Django demo serves, prefix included."""
    return {route.path for route in routes("django")}


def flask_routes() -> set[str]:
    """Every path the Flask demo serves, from the blueprints `app.py` registers."""
    return {route.path for route in routes("flask")}


def fastapi_routes() -> set[str]:
    """Every path the FastAPI demo serves, from the routers `main.py` includes."""
    return {route.path for route in routes("fastapi")}
