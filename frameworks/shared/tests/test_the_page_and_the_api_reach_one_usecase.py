"""Inside ONE demo, the page and the endpoint have to come down onto the SAME use case.

`test_the_demos_serve_the_same_routes.py` compares Django's API against Flask's against FastAPI's.
That is parity HORIZONTALLY, between frameworks, and it is built and it works. Nothing was watching
the other axis: within a single application, does `/orders` decide what `/api/orders` decides? If it
does not, the demo has stopped being a BFF — `/api/X` is no longer the same decision served as JSON,
it is a SECOND implementation of the domain — and the three-column net cannot see it, because three
apps can drift the same way and still agree with each other.

HOW THE JOIN IS MADE, and the shape of it is the whole design. A route is read from source, the
handler it names is resolved, and the handler's CALL GRAPH is walked — through the app's own
`apps.<domain>.usecases` re-export shim, through `apps.<domain>.viewmodels`, into
`shared/viewmodels/` and on — until it reaches a function that is DEFINED in `shared/usecases/` or
`shared/aio/`. That defining module is the operation's identity: `billing.pay_invoice` is
`shared/usecases/billing_usecases.py::pay_invoice` no matter which package re-exported it and no
matter whether the caller took the synchronous twin or the `shared.aio` one.

NOTHING HERE MATCHES ON A NAME, which is the constraint this repository paid three deleted files to
learn. The surface a route belongs to is the path the application actually serves — `/api/...` or
not — read from the mount and the prefix, not from a file called `api.py`. The operation is the
module that holds the `def`, reached by following imports, not two identifiers that look alike. Give
`apps/orders/usecases.py` a re-export of somebody else's function and this reader follows it there;
rename every handler in the demo and it changes nothing.

Two things fell out of anchoring it that way, and both are the anchor earning its keep:

* Django's `/auth/login` and its `/api/auth/login` call `usecases.login` on two different shims, and
  BOTH resolve to `shared/usecases/blog_usecases.py::login`. Read by package name that is one page
  operation and one endpoint operation which never meet; read by definition it is one operation on
  two surfaces, which is what it is.
* The three SSR spellings `test_the_demos_serve_the_same_routes.py` exempts —`/lab` against
  `/lab/list`, and Flask's `/posts` alias— cost this file nothing at all. Both spellings land on
  `lab.index_sections`, so an exemption about how a route is SPELLED cannot reach a comparison made
  on what it CALLS.

WHY READS COUNT HERE AND NOT NEXT DOOR, AND WHY THE OLD WORDING OF THIS PARAGRAPH WAS TOO KIND.
`test_the_pages_and_the_api_do_the_same_things.py` leaves reads out, and its stated reason was that
the two surfaces read in different SHAPES — the pages page and report, the API serves resources — so
demanding one route list would mean handing an API a pager built for a template. That dissolves a
comparison of ROUTES and it says nothing about a comparison of OPERATIONS, which is what this file
went on to measure: of the 23 read divergences it was carrying, THIRTEEN were not a shape at all but
a capability one surface did not have. `billing.paginate_invoices` unreachable from `/api/` was not
an API politely declining a pager; it was a client that could not page invoices, in an application
that also let it PAY an invoice it had no way to read. Of the four operations that paragraph named
as its illustration, two have since closed by being given the missing half and a third
(`stock_of_warehouse`) had never diverged at all. So the shape of the route is free here and the
reach of the operation is not, and that is why this file counts 16 divergences where the other
counts the 7 of them that write.

BOTH FIGURES ARE MEASURED, AND THE PREVIOUS PAIR SAYS WHY THAT MATTERS. They read 49 and 15 for a
while after they had stopped being true — the catalogue below had grown to 45 entries under a
sentence that said 43 — which is the drift a count in prose always ends in: a count written in prose ages exactly like a count written in a table, and neither of them
has a test. The two orders that produce these are `len(_NOT_YET) + len(_BY_DESIGN)` here and
`_divergent_writes` next door, and re-running them is cheaper than trusting this paragraph.

THE BASELINE IS DECLARED AND IT IS NOT A RUBBER STAMP. `_NOT_YET` — debt, with the page or the route
that pays it written next to it — opened at 45 entries and is now EMPTY, which is what E.1 of the
phase 8 plan made sayable: the target is a dictionary an order can look at, not an adjective. All 16
remaining divergences are `_BY_DESIGN`, and the bar for a line there is that the argument existed
BEFORE the divergence was counted, or that it was measured and the measurement is written beside it.

WHAT THE LAST 23 TAUGHT, because it is the part a count cannot carry. Ten of them were decisions
wearing a debt's clothes — a use case pair split by who has already checked existence, a figure the
report page already draws from the identical selector, the unpaged twin of a paged listing — and
each stayed open only because the dictionary it lived in was called "not yet". That is the exact
mistake E.5-bis of the plan documents against six other entries, and it repeated here at scale.
NINE of the thirteen that WERE debt ran the direction nobody had named: the operation was on the
PAGES and missing from the API. An invoice could be paid over JSON and not read over JSON.

`test_no_entry_outlives_its_reason` deletes an entry the day it stops diverging, so the list cannot
rot into a description of the demo as it was; `test_the_two_page_demos_reach_the_same_operations`
stops a divergence being closed in one demo and left open in the other, which is the failure the
per-app assertions cannot see on their own — one app stops diverging and passes, the other still
diverges and is still declared, and nobody is told.
"""

from __future__ import annotations

import ast
import functools
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

# The demos, and the entry point that says which routers each one actually MOUNTS. A router written
# and never mounted answers nothing, so the mount is read rather than assumed — the same join
# `routes.py` makes, for the same reason.
_PAGE_DEMOS = ("django", "flask")
_ALL_DEMOS = ("django", "flask", "fastapi")

_PARAMETER = re.compile(r"<[^>]+>|\{[^}]+\}")

# The packages an operation can be DEFINED in. Two, because the demos come in two colours: Django and
# Flask take the synchronous use case, FastAPI awaits its `shared.aio` twin. The pair is held
# together by `test_async_mirror.py`, so one identity for both is a fact and not a shortcut.
_USECASE_PACKAGES = ("shared.usecases", "shared.aio")
_USECASE_SUFFIX = "_usecases"

# The layers this reader walks THROUGH on its way to a use case. A view model turns rows into
# something a template can print and calls the use case underneath; stopping at it would report that
# the orders pages perform seven operations when they reach thirteen, and would invent a divergence
# that is really a layer.
_TRANSPARENT_PREFIXES = ("apps.", "shared.viewmodels.")


@dataclass(frozen=True)
class _Route:
    """One route of one demo: the path served, and the function that answers it."""

    demo: str
    path: str
    module: str
    handler: str

    @property
    def surface(self) -> str:
        """`api` or `ssr`, decided by the path the application SERVES and by nothing else."""
        return "api" if self.path == "/api" or self.path.startswith("/api/") else "ssr"

    @property
    def where(self) -> str:
        """How this route is named in a catalogue: stable under a change of URL."""
        return f"{self.demo} {self.module}.{self.handler}"


# --- reading source -----------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def _parse(path: Path) -> ast.Module:
    """One parse per file for the whole module: this reader visits some of them many times."""
    return ast.parse(path.read_text(encoding="utf-8"))


def _module_file(demo: str, dotted: str) -> Path | None:
    """The file a dotted module name refers to, or None if it is not one of ours.

    `apps.*` is the demo's own package and resolves under that demo; `shared.*` is the one domain
    layer all three share. Anything else — a framework, the standard library — is not something this
    reader follows, and saying so by returning None is what keeps it from guessing.
    """
    if dotted.startswith("apps."):
        candidate = _ROOT / demo / (dotted.replace(".", "/") + ".py")
    elif dotted.startswith("shared."):
        candidate = _ROOT / (dotted.replace(".", "/") + ".py")
    else:
        return None
    return candidate if candidate.exists() else None


@functools.lru_cache(maxsize=None)
def _bindings(demo: str, dotted: str) -> dict[str, tuple[str, str | None]]:
    """What each name in a module is bound to: `(module, attribute)`, or `(module, None)`.

    The second form is a name that IS a module — `from apps.orders import usecases` — and it is told
    apart from a value by asking the filesystem whether `apps/orders/usecases.py` exists, not by how
    the name is capitalised.
    """
    path = _module_file(demo, dotted)
    if path is None:
        return {}
    found: dict[str, tuple[str, str | None]] = {}
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                submodule = f"{node.module}.{alias.name}"
                found[alias.asname or alias.name] = (
                    (submodule, None)
                    if _module_file(demo, submodule) is not None
                    else (node.module, alias.name)
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found[alias.asname or alias.name] = (alias.name, None)
    return found


@functools.lru_cache(maxsize=None)
def _functions(
    demo: str, dotted: str
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """The functions a module DEFINES at top level, by name."""
    path = _module_file(demo, dotted)
    if path is None:
        return {}
    return {
        node.name: node
        for node in _parse(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _definition_of(
    demo: str, dotted: str, name: str, depth: int = 0
) -> tuple[str, str] | None:
    """Follow re-exports until the module that holds the `def`.

    `apps/taxonomy/usecases.py` is a wall of `from shared.usecases.taxonomy_usecases import X as X`,
    and that wall is the seam this whole file hangs on: it is what lets a view import from its own
    layer while the operation stays defined once. Walking it is what turns two shims into one
    identity. The depth cap is for a cycle rather than for the depth, which is two or three.
    """
    if depth > 8:
        return None
    if name in _functions(demo, dotted):
        return (dotted, name)
    binding = _bindings(demo, dotted).get(name)
    if binding is None:
        return (dotted, name)
    module, attribute = binding
    if attribute is None or module == dotted:
        return None if attribute is None else (dotted, name)
    return _definition_of(demo, module, attribute, depth + 1)


def _operation(dotted: str, name: str) -> str | None:
    """`billing.pay_invoice` for a function defined in a use case module, None for anything else."""
    package, _, module = dotted.rpartition(".")
    if package not in _USECASE_PACKAGES or not module.endswith(_USECASE_SUFFIX):
        return None
    return f"{module[: -len(_USECASE_SUFFIX)]}.{name}"


def _call_target(
    demo: str, dotted: str, node: ast.Call, defined: frozenset[str]
) -> tuple[str, str] | None:
    """Where one call in a function body goes, as `(module, name)`, or None if it leaves our code."""
    call = node.func
    bindings = _bindings(demo, dotted)
    if isinstance(call, ast.Attribute) and isinstance(call.value, ast.Name):
        binding = bindings.get(call.value.id)
        if binding is None or binding[1] is not None:
            return None
        return _definition_of(demo, binding[0], call.attr)
    if isinstance(call, ast.Name):
        if call.id in defined:
            return (dotted, call.id)
        binding = bindings.get(call.id)
        if binding is None or binding[1] is None:
            return None
        return _definition_of(demo, binding[0], binding[1])
    return None


def _operations_reached(
    demo: str, dotted: str, name: str, seen: frozenset[tuple[str, str]] = frozenset()
) -> frozenset[str]:
    """Every operation one function can reach, following calls through the transparent layers."""
    if (dotted, name) in seen:
        return frozenset()
    seen = seen | {(dotted, name)}
    node = _functions(demo, dotted).get(name)
    if node is None:
        return frozenset()
    defined = frozenset(_functions(demo, dotted))
    reached: set[str] = set()
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        target = _call_target(demo, dotted, inner, defined)
        if target is None:
            continue
        module, called = target
        operation = _operation(module, called)
        if operation is not None:
            reached.add(operation)
        elif module.startswith(_TRANSPARENT_PREFIXES):
            reached |= _operations_reached(demo, module, called, seen)
    return frozenset(reached)


# --- reading route tables -----------------------------------------------------------------------


def _normalise(path: str) -> str:
    """One spelling for one path: parameters collapsed, no trailing slash. As `routes.normalise`."""
    return "/" + _PARAMETER.sub("<var>", path).strip("/")


def _literal(node: ast.expr | None) -> str | None:
    """The string a node is, or None if it is anything else. Nothing here evaluates code."""
    return (
        node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        else None
    )


def _django_routes() -> list[_Route]:
    """Django's, from the root urlconf's includes down into each `urlpatterns`.

    The mount cannot be skipped: `apps/auth/urls.py` is mounted at `api/auth/` and
    `apps/auth/web_urls.py` at `auth/`, so the prefix is the only thing that says which surface a
    route belongs to. `apps/blog/urls.py` is the case that settles it — mounted at the empty path,
    it declares the blog's PAGES and its `api/posts/` endpoints in one list.
    """
    routes: list[_Route] = []
    for node in ast.walk(_parse(_ROOT / "django/config/urls.py")):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "path"):
            continue
        if len(node.args) != 2 or not isinstance(node.args[1], ast.Call):
            continue
        included = node.args[1]
        if getattr(included.func, "id", "") != "include" or not included.args:
            continue
        prefix, module = _literal(node.args[0]), _literal(included.args[0])
        if prefix is None or module is None:
            continue
        source = _module_file("django", module)
        if source is None:
            continue
        bindings = _bindings("django", module)
        for entry in ast.walk(_parse(source)):
            if not (
                isinstance(entry, ast.Call)
                and getattr(entry.func, "id", "") in {"path", "re_path"}
                and len(entry.args) >= 2
            ):
                continue
            route = _literal(entry.args[0])
            handler = entry.args[1]
            if route is None or not isinstance(handler, ast.Attribute):
                continue
            if not isinstance(handler.value, ast.Name):
                continue
            binding = bindings.get(handler.value.id)
            if binding is None or binding[1] is not None:
                continue
            routes.append(
                _Route("django", _normalise(prefix + route), binding[0], handler.attr)
            )
    return routes


_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "route"})


def _decorated_routes(
    demo: str, entry: str, mounter: str, factory: str, prefix_argument: str
) -> list[_Route]:
    """Flask's and FastAPI's: a decorated function on an object the entry point mounts."""
    tree = _parse(_ROOT / entry)
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

    routes: list[_Route] = []
    for module, name in sorted(mounted):
        source = _module_file(demo, module)
        if source is None:
            continue
        parsed = _parse(source)
        prefix = ""
        for node in ast.walk(parsed):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                continue
            target = node.targets[0]
            if not (isinstance(target, ast.Name) and target.id == name):
                continue
            if not (
                isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", "") == factory
            ):
                continue
            for keyword in node.value.keywords:
                if keyword.arg == prefix_argument:
                    prefix = _literal(keyword.value) or ""
        for node in parsed.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                attribute = decorator.func
                if not isinstance(attribute, ast.Attribute):
                    continue
                if attribute.attr not in _HTTP_METHODS:
                    continue
                if getattr(attribute.value, "id", "") != name:
                    continue
                route = _literal(decorator.args[0]) if decorator.args else None
                if route is not None:
                    routes.append(
                        _Route(demo, _normalise(prefix + route), module, node.name)
                    )
    return routes


@functools.lru_cache(maxsize=None)
def _routes(demo: str) -> tuple[_Route, ...]:
    """Every route one demo serves, read from its source and never by booting it."""
    if demo == "django":
        return tuple(_django_routes())
    if demo == "flask":
        return tuple(
            _decorated_routes(
                "flask", "flask/app.py", "register_blueprint", "Blueprint", "url_prefix"
            )
        )
    return tuple(
        _decorated_routes(
            "fastapi", "fastapi/main.py", "include_router", "APIRouter", "prefix"
        )
    )


@functools.lru_cache(maxsize=None)
def _reach(demo: str, surface: str) -> frozenset[str]:
    """Every operation one surface of one demo can reach."""
    reached: set[str] = set()
    for route in _routes(demo):
        if route.surface == surface:
            reached |= _operations_reached(demo, route.module, route.handler)
    return frozenset(reached)


def _divergent(demo: str) -> frozenset[str]:
    """The operations one demo can reach from exactly ONE of its two surfaces."""
    pages, api = _reach(demo, "ssr"), _reach(demo, "api")
    return frozenset((pages | api) - (pages & api))


def _domains() -> tuple[str, ...]:
    """The domains an operation can belong to, taken from the use case modules that define them."""
    return tuple(
        sorted(
            path.name[: -len(_USECASE_SUFFIX) - 3]
            for path in (_ROOT / "shared/usecases").glob(f"*{_USECASE_SUFFIX}.py")
        )
    )


# --- what is declared ---------------------------------------------------------------------------

# A demo that serves ONE surface, with why. FastAPI is the JSON demo and has no HTML on purpose, so
# asking it the vertical question would compare a set against an empty one and report every
# operation it has as a divergence. Declared and not skipped quietly: the day this demo grows a
# template, the entry below is what has to be removed for it to be measured.
_ONE_SURFACE_ON_PURPOSE: dict[str, str] = {
    "fastapi": (
        "the ASGI demo answers only JSON, which `test_the_demos_serve_the_same_routes.py` states "
        "as well: SSR is Django against Flask, and a third column here would be blanks"
    ),
}

# Routes whose handler reaches NO operation at all, with why. This is the anti-vacuum list, and it
# earns its maintenance: a page that stops calling a use case — because somebody inlined a selector
# into a view — is the seam breaking in the most complete way there is, and it would otherwise show
# up as a divergence quietly closing.
#
# The shapes are THREE, and the third one arrived with the client-routed demo: a handler that only
# RENDERS a form, a handler that only clears a cookie, and a handler that reads a row somebody else
# already fetched. The first two touch nothing. The third touches nothing IN THE HANDLER, and the
# entry has to say where the fetch actually happened or it reads as the seam breaking.
_TOUCHES_NO_OPERATION: dict[str, str] = {
    "django apps.auth.views.logout": "clears the signed session cookie; no row is read or written",
    "django apps.blog.api.auth_logout": "the JSON half of the same cookie wipe",
    "flask apps.auth.urls.logout": "clears the signed session cookie",
    "flask apps.blog.api.logout": "the JSON half of the same cookie wipe",
    # The third shape, and both entries arrived with `/api/auth/me` — the route a client that routes
    # in the BROWSER cannot work without and an SSR demo never needed, because a rendered page
    # already knows who asked. Each demo answers "who is logged in" its own way, and this route uses
    # the mechanism its demo already had rather than inventing a second one: Django a guard, Flask a
    # `before_app_request` hook. Both resolve the row through `selectors.get_user`, which is where
    # that plumbing has always lived — so the handler itself reaches no operation.
    #
    # Flask's is the stronger case, and it was MEASURED: `_open_session` runs for every request this
    # app serves, JSON included, and its docstring promises to "resolve the logged-in user exactly
    # once". Asking again in the handler broke that promise, and the ORM's own debug panel is what
    # said so — two identical `SELECT ... FROM users WHERE id = %s` and a `1 duplicates` on a route
    # whose whole job is one lookup.
    "django apps.blog.api.auth_me": (
        "reads the session user through `guards.current_user`, the helper every page of this demo "
        "already asks with; the row is resolved by a selector, as it always has been"
    ),
    "flask apps.blog.api.me": (
        "reads `g.current_user`, which the app-wide `_open_session` hook has already resolved; "
        "asking again was a duplicate the debug panel flagged"
    ),
    "fastapi apps.blog.urls.logout": "the ASGI half of the same cookie wipe",
    "flask apps.blog.urls.index": (
        "the root: redirects to the listing or to the login depending on the session, and Django "
        "serves its listing at `/` directly instead"
    ),
    "flask apps.auth.urls.login_form": (
        "Flask splits a form into the GET that draws it and the POST that submits it; the POST next "
        "door reaches `blog.login`. Django answers both verbs in one view, which is why it has no "
        "twin of this entry"
    ),
    "flask apps.auth.urls.register_form": "the GET half of `blog.register`, as above",
    "flask apps.blog.urls.new_post_form": "the GET half of `blog.create_post`, as above",
}

# Operations that reach one surface BY DECISION, quoting the argument this repository already made
# rather than inventing a second one. That is the bar, and it is the only one worth having: an entry
# here is not "nobody built the other half", it is a reason that was written down BEFORE anybody
# counted this divergence — in a use case's docstring, in a selector, in a sibling test — and is
# quoted here rather than re-derived. Where the argument was measured instead of quoted, the comment
# above the entry says what was measured and how, so the next reader can re-run it rather than
# believe it.
#
# The entries fall into eight groups, and the groups matter more than the count: a token has no
# cookie jar; billing's pages are read-only as a section; a pair of use cases split by who has
# already checked existence; a figure the report page already draws from the same selector; the
# unpaged twin of a paged listing; a catalogue the report prints with a column added; a sub-resource
# whose per-parent loop is a named N+1; and a fetch that exists to fill in a form.
_BY_DESIGN: dict[str, str] = {
    # `test_the_pages_and_the_api_do_the_same_things.py::_WRITE_ON_ONE_SURFACE`: "a token is for a
    # client that has no cookie jar; a browser gets a session. The two halves of authentication
    # genuinely belong to different surfaces, which is why the login pages set `user_id` in a signed
    # cookie and never mint a token".
    "auth.issue_token": "DECISION. A token is for a client with no cookie jar; a browser gets a session",
    "auth.revoke_token": "DECISION. The other half of `issue_token`, above",
    # Same file: billing's pages are read-only AS A SECTION, which `test_nav.py::test_billing_is_
    # read_only_and_says_so_by_what_it_does_not_offer` asserts by the actions it refuses to have.
    # The line is about MONEY BEING TYPED: an invoice is raised for what the order came to, and a
    # form where a figure is retyped is the one thing this domain keeps out of one.
    "billing.issue_invoice": "DECISION. `orders.settle` raises the invoice; no page types the figure",
    "billing.pay_invoice": "DECISION. An invoice is settled by an OPERATION, not by a form",
    "billing.subscribe": "DECISION. Billing's pages are read-only as a section, and `test_nav.py` asserts it",
    "billing.cancel_subscription": "DECISION. The other half of `subscribe`, above",
    # --- the twin split by WHO HAS ALREADY ASKED, which the source states in so many words --------
    # `inventory_usecases.stock_history` and `inventory_usecases.movements_of` run the SAME selector
    # over the same pair, and the first one's docstring says why there are two of them: "An endpoint
    # asked for a pair by URL and has to answer 404; a detail page has already fetched the row —that
    # is what it is showing— so repeating the lookup here would be a third statement on every visit
    # to learn what the caller already knows. Same query, different question about who has already
    # asked." Neither surface is short of the ANSWER, which is what this file is a list of. What
    # differs is the existence check, and the existence check is a property of the CALLER.
    "inventory.stock_history": (
        "DECISION. The unchecked half of a documented pair; the API asks the same question through "
        "`movements_of`, which buys the 404 a URL needs and a detail page has already had"
    ),
    "inventory.movements_of": (
        "DECISION. The checked half of the pair above; the pages ask it through `stock_history`"
    ),
    # One step on in the same domain and on the same reasoning. `count_movements` is what the DELETE
    # CONFIRMATION needs — not the movements, the NUMBER of them, so the screen can say what would be
    # orphaned before it offers the button. A JSON client draws no confirmation: it asks for the
    # deletion and `remove_stock` refuses it with `conflict`, which is the same rule at the same
    # moment. Nor is the API short of the figure, since `movements_of` returns the rows it counts.
    "inventory.count_movements": (
        "DECISION. The confirmation screen's cheap COUNT; JSON meets the same rule as `conflict` "
        "from `remove_stock`, and can count `movements_of` if it wants the number"
    ),
    # --- the figure the report page ALREADY prints, out of the SAME selector ----------------------
    # Measured rather than argued from the names. `inventory_usecases.stock_report` fills
    # `StockReport.warehouses` from `selectors.warehouse_stats`, and `orders_usecases.order_report`
    # fills `OrderReport.states` from `selectors.orders_per_state` — the very two functions the use
    # cases below wrap, and both figures are drawn by `inventory/report` and `orders/report`. What
    # only JSON has is the figure ON ITS OWN, without the other five of its report, and that is
    # something a client COMPOSES rather than a question a reader cannot ask. The page that closed
    # it would be one table lifted out of a page that already has it.
    "inventory.warehouse_stats": (
        "DECISION. `stock_report` draws these figures on `inventory/report` from the same "
        "`selectors.warehouse_stats`; the bare use case is one row of that report, for a client "
        "that composes"
    ),
    "orders.orders_per_state": (
        "DECISION. `order_report` draws the histogram on `orders/report` from the same "
        "`selectors.orders_per_state`; as above"
    ),
    # --- the UNPAGED whole collection, which is the thing a pager is put in front of --------------
    # Neither of these is a question the pages cannot ask. `paginate_orders` takes the same `state`
    # filter `list_orders` takes and `orders/list` passes it; `paginate_invoices` takes `paid` and
    # `billing/list` passes it through `parse_paid`, so `?paid=open` IS the arrears list, on a
    # screen, today. What the pages do not have is the collection with no LIMIT on it — and a page
    # for that is the unbounded listing the pager exists to prevent.
    "orders.list_orders": (
        "DECISION. The unpaged collection; `orders/list` asks the same question through "
        "`paginate_orders`, and a listing with no LIMIT is what the pager was put in front of"
    ),
    "billing.unpaid_invoices": (
        "DECISION. As above — `billing/list?paid=open` reaches the arrears through "
        "`paginate_invoices`; this is the same rows unbounded, for a collector"
    ),
    # --- the catalogue that is already on a page, with a column added ------------------------------
    # Measured to the character: `billing_selectors.plans_query` and `plan_stats_query` are the SAME
    # query — `SnakeQuery(Plan).order_by(Plan.price_cents.asc())` — and `billing_report` runs the
    # second one through `annotate`. So `billing/report` prints every plan `list_plans` would return,
    # with the id, name and price `plan_dict` publishes and the subscriber count beside them; a plan
    # nobody subscribes to still comes back with a zero, so nothing is filtered out either. A plans
    # page would be that table with a column taken off it.
    "billing.list_plans": (
        "DECISION. `billing/report` prints the whole catalogue from the identical query with the "
        "subscriber count added; a plans page would be that table minus a column"
    ),
    # --- the sub-resource whose per-parent loop is the N+1 its sibling was written to replace -----
    # `invoices_of_customer` says it outright: "The one above answers for a subscription; asking it
    # per subscription is the N+1 this replaces." The page that wants a customer's invoices —
    # `orders/operate` — holds the CUSTOMER and takes the one-statement version. The endpoint answers
    # a URL that names ONE subscription, so it asks for one. Giving this to the pages means a screen
    # that loops it per subscription, which is the read the sibling exists to kill.
    "billing.invoices_of_subscription": (
        "DECISION. The per-subscription read; the pages hold a CUSTOMER and take "
        "`invoices_of_customer`, whose docstring names the per-subscription loop as the N+1 it "
        "replaces"
    ),
    # --- the fetch that exists to PREFILL a form ---------------------------------------------------
    # `blog_usecases.editable_post` reads a post for one purpose: to put its title and body into the
    # edit form's fields, having first refused a post that is not the author's. The API draws no
    # form, and its PUT makes the identical ownership decision inside `edit_post` — same refusal, one
    # round trip instead of two. It is the shape the GET halves in `_TOUCHES_NO_OPERATION` above
    # already have, one layer up: there the handler touches no row at all, here it touches the row a
    # form is about to show.
    "blog.editable_post": (
        "DECISION. The edit form's prefill; the API has no form to draw and `edit_post` makes the "
        "same ownership refusal at the moment of the write"
    ),
}

# THE BASELINE, and it is DEBT rather than a decision: every line here is an operation one surface of
# a demo can perform and the other cannot, waiting on the pass that closes them.
#
# It is written down instead of asserted away because a net that goes red with forty-three failures
# on the day it is written is a net somebody silences. What it buys, kept: the list cannot GROW
# without a failure that names the operation, and it cannot go STALE either — the moment a page
# closes one of these, `test_no_entry_outlives_its_reason` demands the line be struck. The target of
# E.4 is this dictionary EMPTY, which is a thing an order can check and no adjective can fake.
#
# **IT IS EMPTY.** It opened at 45 entries under 51 divergences. E.3 struck 22 of them by giving
# `accounts`, `auth`, `content` and `engagement` the sections they had never had — four whole domains
# with no page at all, and `auth` was invisible to the older net because that one reads a domain by
# its PACKAGE: `django/apps/auth/views.py` calls `usecases.login`, so `auth` looked like a domain
# with pages. Followed to the definition those pages are `blog_usecases.login`, and the auth domain
# proper — tokens and sessions — had never been drawn.
#
# THE LAST 23 WERE A DIFFERENT PROBLEM AND THEY SPLIT ALMOST IN HALF, which is the finding worth
# leaving here. TEN were never debt: they are decisions, and every one of them is in `_BY_DESIGN`
# above with what was MEASURED beside it rather than with an opinion. THIRTEEN were debt, and NINE
# of those thirteen ran the direction nobody had named — the operation was on the PAGES and missing
# from the API. Billing could be paid over JSON and not read over JSON; the inventory pair could be
# written and deleted and not fetched; two whole reports and two exports had a screen and no
# endpoint. Counted before the work started, ELEVEN of the twenty-three were an endpoint with no
# screen and TWELVE were a page with no endpoint, so a summary that spoke only of "operations that
# live in `/api/` alone" would have named under half of them — which is what a figure carried in
# somebody's head does to a list that has a reader.
#
# EMPTY IS NOT FINISHED, IT IS A CONTRACT. `test_an_operation_reaches_both_surfaces_or_is_written_
# down` puts the next divergence here or in `_BY_DESIGN` the day somebody writes it, and the
# comments below are kept — the list is empty, its history is not, and the arguments are what stop
# the next reader re-deriving a decision that was already made.
_NOT_YET: dict[str, str] = {
    # --- accounts, auth, content and engagement: CLOSED by E.3 -----------------------------------
    # Twenty-two entries stood here, and four of them were whole domains with no page at all. Each
    # one is gone because a page now reaches the SAME use case the endpoint reaches, which is what
    # `test_no_entry_outlives_its_reason` demands the moment it becomes true. What closed them, for
    # the next person reading a shorter list than the one this file was written with:
    #
    #   * `accounts` grew a role directory and a grants screen shaped like `taxonomy`'s, which also
    #     retired `blog.user_stats` — the directory needed a list of people and the blog's typed
    #     aggregate already was one.
    #   * `content` grew a listing and a sheet that draws the SAME table twice on purpose: the
    #     deferred timeline above the full revisions, which is the only place in the demos where the
    #     cost of `defer()` is visible rather than described.
    #   * `engagement` grew a traffic board, a sheet with the three writes on it, and its section —
    #     which is what moved `stream_visits` across. The entry below it said so before the section
    #     existed: the export was JSON-side because this domain had nowhere to hang it, never
    #     because a file belongs there.
    #   * `auth` grew its FIRST screen ever. It had looked like a domain with pages because
    #     `django/apps/auth/views.py` calls `usecases.login`; followed to the definition that is
    #     `blog_usecases.login`, and tokens and sessions had never been drawn. The ledger reads
    #     them; minting and revoking stay in `_BY_DESIGN` above, untouched.
    # --- billing: the READS, on both sides ---------------------------------------------------------
    # The section's four WRITES are the decision quoted in `_BY_DESIGN`; these are not covered by it.
    # A read reachable from one surface only is still a client that cannot ask a question the other
    # surface answers, and the "different shapes" argument that excuses two ROUTE lists does not
    # excuse an operation that one side cannot reach at all.
    #
    # ALL EIGHT ARE GONE and they went two different ways, which is the distinction E.1 of the phase
    # 8 plan exists to make and which this section is now the worked example of.
    #
    # THREE WERE NEVER DEBT. They are in `_BY_DESIGN` above with what was measured beside them:
    # `list_plans` is printed in full by `billing/report` out of a query identical to its own,
    # `unpaid_invoices` is `billing/list?paid=open` with the LIMIT taken off, and
    # `invoices_of_subscription` is the per-parent loop `invoices_of_customer` was written to kill.
    #
    # THE OTHER FIVE WERE DEBT, and of a kind the summary of this file had never named: the operation
    # was on the PAGES and missing from the API. A client could pay an invoice it had no way to READ,
    # could not list all invoices at all, and had no report — while `orders` had published its pager,
    # its report and its export for a phase already. They closed with five JSON routes over the very
    # use cases the pages go through, which is the cheap half of this net's promise and the half
    # nobody had collected.
    # --- blog: the one that does not meet ----------------------------------------------------------
    # `blog.user_stats` used to be here — "the per-author counters answer only as JSON; no page
    # prints them" — and it came off without anybody going looking for it: `accounts` needed a
    # directory of people to hang its grants pages off, and the blog's typed aggregate already was
    # one. That is the shape a closure is supposed to have.
    # `blog.editable_post` stood here too — "the edit form's own fetch: the API decides the same
    # thing inside `edit_post`" — and that sentence WAS the argument. It is in `_BY_DESIGN` now,
    # said the way a decision is said instead of the way a debt is.
    # --- inventory: seven of the eleven, and the domain with the most of both ---------------------
    # Four came off with an argument rather than with a page, all four measured: `movements_of` and
    # `stock_history` are one question split by who has already checked the pair exists —which the
    # use case says in its own docstring— `count_movements` is that split one step on, and
    # `warehouse_stats` is a figure `inventory/report` already draws from the very same selector.
    #
    # Four MORE came off with a route rather than an argument, and they were all the same shape read
    # from the JSON side: `get_stock` — the pair `/api/inventory/warehouses/{id}/stock/{sku}` could
    # be written and deleted and not READ — plus the pager, the report and the export, each of which
    # `orders` had published for a while and `inventory` had not.
    #
    # The last three closed with two PAGES, and both were a question rather than a screen for a
    # method. `low_stock` reads the read-only VIEW and now has the reorder screen an inventory
    # section with a report and an export had somehow never had. `get_warehouse` and
    # `stock_with_movements` closed TOGETHER on one sheet, which is what said the page was real: the
    # header and the warehouse's stock with every pair's movements PREFETCHED — the to-many over a
    # composite key, answered in one statement where the pages had been answering it one click per
    # SKU.
    # --- orders: one read the API had and no page asked for ----------------------------------------
    # Two of the three were never debt. `list_orders` is the collection with no LIMIT on it and the
    # pages ask the same question through `paginate_orders`, which takes the same filter;
    # `orders_per_state` is drawn by `orders/report` out of `selectors.orders_per_state`, which is
    # the function the use case wraps. Both are in `_BY_DESIGN` with what was measured.
    #
    # `orders_of_customer` was the one that was really missing, and the measurement that settled it
    # is worth keeping: `paginate_orders` has taken a `customer_id` all along and NO page ever passed
    # it, so "narrow the orders to one customer" was a question the demo could answer and did not.
    # The customer sheet asks it, and it hangs off the roll-call the report already prints.
}


# --- the assertions -------------------------------------------------------------------------------


def _pytest_params() -> list[tuple[str, str]]:
    """One case per demo that serves both surfaces and per domain, so a failure names both."""
    return [
        (demo, domain)
        for demo in _PAGE_DEMOS
        if demo not in _ONE_SURFACE_ON_PURPOSE
        for domain in _domains()
    ]


def test_a_demo_serves_both_surfaces_or_says_which_one_it_does_not() -> None:
    """No demo drops out of the vertical comparison in silence, which is the vacuous run.

    A demo with no pages contributes an empty SSR set, reports every endpoint it has as a
    divergence, and would drown the baseline; a demo that LOST its pages would do the same and mean
    something else entirely. Declaring the first is what makes the second visible.
    """
    silent = sorted(
        demo
        for demo in _ALL_DEMOS
        if demo not in _ONE_SURFACE_ON_PURPOSE
        and not (_reach(demo, "ssr") and _reach(demo, "api"))
    )

    assert silent == [], (
        f"these serve only one surface and nothing says that was the intention: {silent}. Either "
        f"the demo lost a surface, or the reader stopped resolving one — add it to "
        f"`_ONE_SURFACE_ON_PURPOSE` with the reason only if it is really the first."
    )


def test_every_route_reaches_a_use_case_or_is_written_down() -> None:
    """Each route resolves to at least one operation, or it is named with why it resolves to none.

    This is the seam at its most basic: a page whose handler reaches no use case is not serving the
    domain layer at all. It is also this file's own anti-vacuum net — a reader that stopped
    following calls would report every route as reaching nothing, and the list below is far too
    short to absorb that.
    """
    silent = sorted(
        route.where
        for demo in _ALL_DEMOS
        for route in _routes(demo)
        if not _operations_reached(demo, route.module, route.handler)
        and route.where not in _TOUCHES_NO_OPERATION
    )

    assert silent == [], (
        f"these routes reach no use case: {silent}. Either the handler stopped going through the "
        f"domain layer — which is the seam breaking — or it genuinely touches no row, in which case "
        f"add it to `_TOUCHES_NO_OPERATION` with the reason."
    )


def test_no_declared_route_still_reaches_a_use_case() -> None:
    """An entry in `_TOUCHES_NO_OPERATION` disappears the day its handler starts calling one.

    Same bargain the rest of this repository's catalogues strike: an excuse expires when it is
    spent, or the list stops describing the demo and starts describing a memory of it.
    """
    everywhere = {
        route.where: (demo, route) for demo in _ALL_DEMOS for route in _routes(demo)
    }
    stale = sorted(
        where
        for where in _TOUCHES_NO_OPERATION
        if where in everywhere
        and _operations_reached(
            everywhere[where][0],
            everywhere[where][1].module,
            everywhere[where][1].handler,
        )
    )
    gone = sorted(where for where in _TOUCHES_NO_OPERATION if where not in everywhere)

    assert stale == [], (
        f"these are recorded as reaching no use case and now reach one: {stale}. Strike them off."
    )
    assert gone == [], (
        f"these are recorded as routes and no demo serves them any more: {gone}."
    )


def test_the_two_catalogues_do_not_overlap() -> None:
    """Nothing is both a decision and a debt, because the two ask opposite things of the reader.

    `_BY_DESIGN` says stop looking; `_NOT_YET` says here is the page that closes it. An operation in
    both would tell whoever reads it next that the question is settled AND open, and the reason a
    catalogue is a mapping rather than a set is precisely so a decision can be told from an
    oversight.
    """
    both = sorted(set(_BY_DESIGN) & set(_NOT_YET))

    assert both == [], (
        f"these are declared as a decision and as debt at once: {both}. Pick one — the entry either "
        f"has an argument behind it or it is waiting for a page."
    )


@pytest.mark.parametrize(("demo", "domain"), _pytest_params())
def test_an_operation_reaches_both_surfaces_or_is_written_down(
    demo: str, domain: str
) -> None:
    """Inside one demo, an operation the pages can perform is one the API can perform, and back.

    BOTH directions, because the two failures are the same failure seen from opposite sides. A
    reader who has placed an order through the pages and reaches for the endpoint that bills it
    should not find it missing; and an endpoint with no screen is a capability the demo teaches in
    JSON and hides in HTML. Neither is a shape difference — the shapes were normalised away when the
    join was made on the use case rather than on the URL.
    """
    unnamed = sorted(
        operation
        for operation in _divergent(demo)
        if operation.startswith(f"{domain}.")
        and operation not in _BY_DESIGN
        and operation not in _NOT_YET
    )

    assert unnamed == [], (
        f"in the {demo} demo these are reachable from one surface only: {unnamed}. Either give the "
        f"other surface the operation — one more presentation over the SAME use case, which is what "
        f"E.3 of the phase 8 plan is — or add it to `_NOT_YET` with the page that would close it, "
        f"or to `_BY_DESIGN` if there is a written argument for the split. A rationale you do not "
        f"have is not an honest entry; 'NOT AUDITED' is."
    )


def test_no_entry_outlives_its_reason() -> None:
    """An entry disappears the day the operation reaches both surfaces of every demo that has both.

    Without this the baseline becomes a description of the demos as they were on the day somebody
    last looked, which reads exactly like a description of the demos. It is also what makes E.4's
    target checkable: `_NOT_YET` empty means the work is done, and it cannot be emptied by editing.
    """
    diverging = frozenset().union(
        *(
            _divergent(demo)
            for demo in _PAGE_DEMOS
            if demo not in _ONE_SURFACE_ON_PURPOSE
        )
    )
    settled = sorted(
        entry for entry in (set(_BY_DESIGN) | set(_NOT_YET)) if entry not in diverging
    )

    assert settled == [], (
        f"these are recorded as reachable from one surface only and no longer are: {settled}. "
        f"Strike them off — a catalogue that keeps closed entries stops being read, and one of "
        f"these is what 'E.3 closed a domain' looks like from here."
    )


def test_the_two_page_demos_reach_the_same_operations() -> None:
    """Django and Flask agree, surface by surface, on which operations they can perform.

    The per-demo assertions above cannot see a divergence closed in ONE demo: the demo that grew the
    page stops diverging and passes, the other still diverges and is still declared, and nothing is
    said. This is the net that says it. It is also what lets one baseline serve both demos honestly
    — measured when this was written, the two reach exactly the same 59 operations from their pages
    and the same 84 from their APIs.
    """
    mismatched = {
        surface: sorted(
            (_reach("django", surface) | _reach("flask", surface))
            - (_reach("django", surface) & _reach("flask", surface))
        )
        for surface in ("ssr", "api")
    }

    assert mismatched == {"ssr": [], "api": []}, (
        f"the two page demos no longer reach the same operations: {mismatched}. One of them grew or "
        f"lost something the other did not, and until they agree the baseline in this file is "
        f"describing one demo and excusing the other."
    )
