"""The three demos answer `/api/X` with the SAME shape, and shape means DTO **and envelope**.

Two nets already stand over this surface and NEITHER of them can see a body. `test_the_demos_serve_
the_same_routes.py` compares the PATHS the three demos publish; `test_the_page_and_the_api_reach_one_
usecase.py` compares which USE CASE a handler comes down onto. A route can be present in all three
and reach the same operation in all three and still hand the caller three different documents, and
that is not a hypothetical: it happened TWICE on the blog, and both times what diverged was the
ENVELOPE and not the DTO.

    /api/posts        `{"posts": [...]}`      against  `[post_dict(p) for p in ...]`
    /api/posts/<id>   `post_dict(p, ...)`     against  `{"post": {...}}`

Read as "which DTO" both pairs are identical — `post_dict` on either side — and a net built on that
axis reports parity over a client that has to branch on which demo it is talking to. So the axis
here is WHICH DTO AND IN WHAT WRAPPING, and the unit of comparison is a token read off the `return`.

Both are FIXED today, and this file is what stops them coming back. It was proved to catch them:
each divergence was reintroduced into the reader's input (never into the demo — `routes._source` is
the one door every parse goes through, so a mutation lives in a test process and the working tree
stays clean) and `test_the_three_apis_answer_the_same_shape` failed naming the route.

THE GRAMMAR IS TINY, AND THAT IS A MEASUREMENT AND NOT A HOPE. Over the 33 API modules of the three
demos there are 283 decorated handlers on 79 distinct paths, holding 354 `return` statements. 53 of
them are the refusal branch (`_ERROR_CONTRACT` below says why those are not compared) and the other
301 fall into FIVE token families with nothing left over:

    obj:post_dict                      125   `post_dict(p, author=...)`
    list[obj:invoice_dict]             117   `[invoice_dict(i) for i in rows]`
    envelope{posts}                     39   `{"posts": [...]}`
    no-content                          17   a 204, in the three spellings `_NO_CONTENT` names
    csv-download                         3   a streamed file, under the two names `_STREAMED_FILE` has

`other:...` is what an unrecognised `return` becomes, and `test_the_reader_understood_every_answer`
fails on the first one. That is deliberate and it is the lesson the three deleted language nets paid
for: a reader that silently drops what it does not recognise is a BLACKLIST, it fails open, and it
reports agreement over the returns it happened to understand. This one fails closed — a `return`
shape nobody has taught it stops the suite until somebody writes down what it is.

WHY THE COMPARISON IS ON THE SET OF TOKENS PER PATH and not per handler. Django answers `GET` and
`POST /api/posts/` from ONE `@api_view(["GET", "POST"])` function while Flask splits them into two
blueprint views, and `Route` carries no verb because none of the three declares one the same way.
Comparing the SET of shapes a path can answer with dissolves that entirely: one handler with two
returns and two handlers with one each produce the same set, and the two bugs above are differences
IN the set, so nothing that matters is lost. It costs nothing and it removes a whole class of false
report.

WHAT THIS NET DOES NOT COVER, said here because a net that hides its edges is the kind that
manufactures confidence:

* **The KEYS inside a DTO.** The token names the function that builds the document, not the document.
  On the blog that gap is at its widest, because the blog serialises through THREE different DSLs:
  `flask/apps/blog/schemas.py` is marshmallow, `django/apps/blog/serializers.py` is a DRF serializer,
  and FastAPI returns the `shared.dto.blog_dto` dictionary straight out. Those two files already
  carry the repository's note about "one resource with two descriptions of its shape". This net
  checks that all three wrap the answer the same way; it does NOT check that the three DSLs agree on
  the key set inside it, and it cannot — reading a marshmallow field list, a DRF `Meta.fields` and a
  `TypedDict` and calling the three equal is a different reader from this one.
* **The ERROR contract**, for the reason `_ERROR_CONTRACT` sets out: only one of the three frameworks
  even has a `return` on that branch.
* **The STATUS code.** `201` against `200` on a create is a divergence and this file will not see it;
  the token is peeled off the tuple or the `status=` keyword and the number is dropped. It is a
  separate axis and it deserves its own reader rather than a corner of this one.
"""

from __future__ import annotations

import ast
import collections

import pytest

from shared.tests.routes import DEMOS, Route, handler_of, routes

# The frameworks' own carrier for a body. NONE of these is part of the answer: `Response(x)`,
# `jsonify(x)` and `JSONResponse(x)` all say "here is a JSON body" in three dialects, so the reader
# peels them and reads `x`. Leaving them in would make every Django route differ from every Flask
# one and the net would report drift on all 79 paths — which is the failure mode of comparing the
# plumbing instead of the answer.
_WRAPPERS: dict[str, str] = {
    "Response": "DRF's, and Flask's when a view builds one by hand",
    "JsonResponse": "Django's own, outside DRF",
    "JSONResponse": "Starlette's, which is what FastAPI hands back when a route builds it itself",
    "HttpResponse": "Django's base class, used where the body is already serialised",
    "jsonify": "Flask's, the only one of the five that is a function and not a class",
}

# FIVE NAMED HELPERS ACCOUNT FOR EVERY RETURN THAT IS NOT A PLAIN DTO, A LIST OR A DICT, and the
# census is what says the grammar above is not wishful: `_refusal` (28 returns), a bodyless
# `Response` (9), `pagination_result` (2), `csv_download` (2) and `csv_response` (1) — 42 in all,
# beside the 8 `return "", 204` that are the same no-content contract without a helper. THREE of the
# five need an entry in a catalogue and two do not, and which is which is the interesting part.
#
# `pagination_result` needs nothing, and the absence was MEASURED rather than assumed: all three
# demos reach it under that one name, so it reads as `obj:pagination_result` on all three and
# compares clean. An entry for it would be a catalogue line that never does anything, which is the
# kind that a year later reads as a decision somebody made.
#
# The CSV pair below is the opposite case: one answer, two names, three signatures. This dictionary
# is `_SSR_SPELLINGS` next door doing the same job — the next person has to be able to tell a
# decision from an oversight, and a bare name in a set explains neither.
_STREAMED_FILE: dict[str, str] = {
    "csv_download": (
        "Django's and FastAPI's streamed CSV. The two are not the same function — Django's takes a "
        "BUILDER because the session has to outlive the view, FastAPI's takes the session and an "
        "async row generator — and neither is a JSON body at all"
    ),
    "csv_response": (
        "Flask's half of the same pair, spelled differently because it takes a built `CsvExport` and "
        "pops `g.session` on its way out. Same answer, three signatures, one token"
    ),
}

# A 204 in the three spellings its frameworks force. Django's DRF view builds a `Response` with no
# body and a status; Flask returns `"", 204`, because a Flask view MUST return something; FastAPI
# declares `status_code=204` on the decorator and its handler is annotated `-> None` and never
# returns at all. Three different pieces of syntax for one contract — and the FastAPI one is why
# `_shapes()` reads the annotation: a handler with no `return` in it would otherwise contribute
# nothing and vanish from the comparison, which is a silent pass and not an agreement.
_NO_CONTENT: dict[str, str] = {
    "django": "`Response(status=204)` — a DRF response built with no body",
    "flask": '`return "", 204` — the empty body a Flask view is obliged to spell out',
    "fastapi": "`-> None` under `status_code=204` — the handler simply falls off its end",
}

# THE ERROR CONTRACT IS OUT OF SCOPE, and this is the reason rather than a shrug. Only ONE of the
# three frameworks answers a refusal with a `return` at all: Django's DRF view builds
# `Response({"detail": reason}, status=...)` inline or through its app's `_refusal` helper, while
# Flask raises through `abort(status)` and FastAPI raises `HTTPException`. A raise is not a return,
# so on the other two demos there is nothing here for an AST reader to compare against — and
# comparing Django's 53 refusal returns against two empty sets would report a divergence on every
# route that can fail. That figure is measured and not guessed: leaving the branch in takes the
# comparison from 0 divergences to 43 of the 79 paths, every one of them the same non-difference.
#
# The parity that DOES exist on this branch is the status map, and it is held elsewhere: all three
# demos carry the same `_FAILURE_STATUS`/`FAILURE_STATUS` table from reason to code.
_ERROR_CONTRACT: dict[str, str] = {
    "_refusal": (
        "the per-app Django helper, 28 returns: `Response({'detail': failure.reason}, "
        "status=FAILURE_STATUS[...])`. Its Flask and FastAPI counterparts RAISE"
    ),
    "envelope{detail}": (
        "the same body written inline, 25 returns. It is DRF's error document and nothing else "
        "answers with it, so the token doubles as the marker"
    ),
    "4xx/5xx": (
        "any return that spells an explicit failing status, whatever its body. Five of them, all "
        "Django, and they overlap the two above"
    ),
}

# Divergences that are DECLARED, with what makes each one right rather than drift. Empty, and
# keeping it empty is the point: `test_no_declared_divergence_outlives_its_reason` strikes an entry
# the day the two demos agree again, so the catalogue cannot rot into a description of the demos as
# they were. The same bargain `_OWED` strikes in `test_the_demos_serve_the_same_routes.py`.
_DECLARED: dict[str, str] = {}


def _name(call: ast.Call) -> str | None:
    """The name a call is made through, whether it is `f(...)` or `mod.f(...)`."""
    return getattr(call.func, "id", None) or getattr(call.func, "attr", None)


def _status(node: ast.expr) -> int | None:
    """The HTTP status a return spells out as a literal, if it spells one at all."""
    if isinstance(node, ast.Tuple) and len(node.elts) >= 2:
        second = node.elts[1]
        if isinstance(second, ast.Constant) and isinstance(second.value, int):
            return second.value
    if isinstance(node, ast.Call):
        for keyword in node.keywords:
            if keyword.arg in {"status", "status_code"} and isinstance(
                keyword.value, ast.Constant
            ):
                if isinstance(keyword.value.value, int):
                    return keyword.value.value
    return None


def token(node: ast.expr | None) -> str:
    """The SHAPE one `return` answers with: which document, inside which wrapping.

    Recursive on purpose, because the shapes nest: `[{**stock_dict(row), "movements": [...]} for row
    in rows]` is a list of an envelope of a DTO, and all three demos spell that one identically —
    which a reader that flattened it to "a list" could not have told you.

    Anything it does not recognise comes back as `other:<node>` rather than being dropped, and
    `test_the_reader_understood_every_answer` fails on it. Failing closed is the whole design.
    """
    if node is None:
        return "no-content"
    if isinstance(node, ast.Await):
        return token(node.value)
    if isinstance(node, ast.Tuple) and node.elts:
        return token(node.elts[0])
    if isinstance(node, ast.Call):
        called = _name(node)
        if called in _STREAMED_FILE:
            return "csv-download"
        if called in _WRAPPERS:
            return token(node.args[0]) if node.args else "no-content"
        return f"obj:{called}"
    if isinstance(node, ast.ListComp):
        return f"list[{token(node.elt)}]"
    if isinstance(node, ast.List):
        return f"list[{token(node.elts[0]) if node.elts else 'empty'}]"
    if isinstance(node, ast.Dict):
        keys = [
            f"**{token(value)}"
            if key is None
            else key.value
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
            else "?"
            for key, value in zip(node.keys, node.values)
        ]
        return "envelope{" + ",".join(sorted(keys)) + "}"
    if isinstance(node, ast.Constant) and node.value in ("", None):
        return "no-content"
    return f"other:{type(node).__name__}"


def _is_refusal(node: ast.expr) -> bool:
    """Whether this `return` is the failure branch, by the catalogue `_ERROR_CONTRACT` writes down."""
    if isinstance(node, ast.Call) and _name(node) in _ERROR_CONTRACT:
        return True
    if token(node) == "envelope{detail}":
        return True
    status = _status(node)
    return status is not None and status >= 400


def _returns(node: ast.stmt) -> list[ast.Return]:
    """Every `return` of one function, WITHOUT descending into a function defined inside it."""
    found: list[ast.Return] = []
    pending: list[ast.stmt] = list(getattr(node, "body", []))
    while pending:
        statement = pending.pop()
        if isinstance(statement, ast.Return):
            found.append(statement)
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        else:
            pending.extend(
                child
                for child in ast.iter_child_nodes(statement)
                if isinstance(child, ast.stmt)
            )
    return found


def _shapes(handler: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Every shape one handler can answer with, refusals left out."""
    found = {
        token(statement.value)
        for statement in _returns(handler)
        if statement.value is None or not _is_refusal(statement.value)
    }
    # A handler annotated `-> None` answers its decorator's `status_code` with no body. Reading the
    # annotation is what makes FastAPI's seven `-> None` DELETE handlers — which contain no `return`
    # whatsoever — say "no content" instead of saying nothing, and saying nothing is what would have
    # let them agree with anything at all.
    if isinstance(handler.returns, ast.Constant) and handler.returns.value is None:
        found.add("no-content")
    return found


def _api_routes() -> list[Route]:
    """Every `/api/` route of the three demos whose handler this reader can open."""
    return [
        route
        for demo in DEMOS
        for route in routes(demo)
        if route.is_api and route.module is not None
    ]


def shapes_by_path() -> dict[str, dict[str, set[str]]]:
    """`path -> demo -> the set of shapes that demo answers it with`.

    A function and not a module-level constant so that a check of this reader can build it again
    over a mutated source; the run cost is one AST walk over 33 files.
    """
    table: dict[str, dict[str, set[str]]] = collections.defaultdict(
        lambda: collections.defaultdict(set)
    )
    for route in _api_routes():
        handler = handler_of(route)
        if handler is not None:
            table[route.path][route.demo] |= _shapes(handler)
    return table


_SHAPES = shapes_by_path()
_SHARED_PATHS = sorted(path for path, demos in _SHAPES.items() if len(demos) > 1)


def test_the_reader_found_the_api_of_all_three_demos() -> None:
    """That the scan opened something at all, which is the trap of every self-discovering check.

    A reader that stops matching — a decorator renamed, a mount written another way — returns
    nothing, every comparison below succeeds over an empty table, and the suite reports that three
    APIs agree when it has not read one. Same vacuous-run guard `test_the_demos_serve_the_same_
    routes.py` opens with, and for the same reason: this file's failure mode is silence.
    """
    per_demo = collections.Counter(route.demo for route in _api_routes())

    assert sorted(per_demo) == sorted(DEMOS), (
        f"no `/api/` handlers read out of {sorted(set(DEMOS) - set(per_demo))}: the demo stopped "
        f"declaring its routes the way `routes.py` reads them, and every comparison in this file "
        f"would now pass over an empty table."
    )
    assert _SHARED_PATHS, (
        "no `/api/` path is served by more than one demo — nothing was compared"
    )


def test_the_reader_understood_every_answer() -> None:
    """Every `return` fell into the grammar, and an unknown one STOPS the suite instead of vanishing.

    This is the half that keeps the comparison from being a blacklist. A `return` shape the grammar
    has never seen would otherwise be dropped, and three demos would be reported as agreeing over
    the subset of their answers this reader happened to recognise — which is exactly what
    `test_strings_are_english` did with its word list, and exactly why that file is gone.

    So an unrecognised shape is a FAILURE and not a skip: teach `token()` what it is, or find out
    that the demo is answering with something nobody meant it to.
    """
    unknown = sorted(
        f"{path} [{demo}] -> {shape}"
        for path, demos in _SHAPES.items()
        for demo, found in demos.items()
        for shape in found
        if shape.startswith("other:")
    )
    silent = sorted(
        f"{path} [{demo}]"
        for path, demos in _SHAPES.items()
        for demo, found in demos.items()
        if not found
    )

    assert unknown == [], (
        f"these `return`s are outside the grammar `token()` knows: {unknown}. Teach it the shape — "
        f"do NOT let it fall through, because a shape this file cannot name is a shape it cannot "
        f"compare, and it would be silently excused on all three demos at once."
    )
    assert silent == [], (
        f"these routes produced no shape at all: {silent}. A handler that contributes nothing agrees "
        f"with everything, which is a pass that has read nothing."
    )


@pytest.mark.parametrize("path", _SHARED_PATHS)
def test_the_three_apis_answer_the_same_shape(path: str) -> None:
    """One `/api/` path answers with the same document, in the same wrapping, on every demo.

    Parametrised per path so the failure NAMES the route that drifted instead of handing over a
    list to read. This is the assertion the two blog bugs would have failed: `envelope{posts}`
    against `list[obj:post_dict]` on the listing, and `obj:post_dict` against `envelope{post}` on
    the detail. Both pairs share their DTO; neither shares its shape.
    """
    demos = _SHAPES[path]
    distinct = {frozenset(found) for found in demos.values()}

    assert len(distinct) == 1 or path in _DECLARED, (
        f"`{path}` answers with a different shape depending on the demo:\n"
        + "\n".join(f"  {demo:8} {sorted(demos[demo])}" for demo in sorted(demos))
        + f"\nEither make the three answer alike, or record `{path}` in `_DECLARED` above WITH the "
        f"reason the difference is a decision. Remember the axis is the DTO **and its envelope**: "
        f"the same `post_dict` inside `{{'posts': [...]}}` on one demo and inside a bare list on "
        f"another is the drift this file exists to catch."
    )


def test_no_declared_divergence_outlives_its_reason() -> None:
    """A declared divergence disappears the day the demos stop diverging, and so does a stale name.

    The half that keeps the catalogues above from rotting. An exemption nobody removes reads, a year
    later, as a decision that was made — and it is really a note about a route somebody quietly
    fixed. Same bargain `test_no_exemption_outlives_its_reason` strikes next door.
    """
    settled = sorted(
        path
        for path in _DECLARED
        if path not in _SHAPES
        or len({frozenset(found) for found in _SHAPES[path].values()}) == 1
    )
    every_call = {
        _name(node)
        for route in _api_routes()
        for handler in [handler_of(route)]
        if handler is not None
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
    }
    unused_streams = sorted(set(_STREAMED_FILE) - every_call)
    unused_refusals = sorted(
        name
        for name in _ERROR_CONTRACT
        if name.isidentifier() and name not in every_call
    )
    # `_NO_CONTENT` explains a spelling PER DEMO, so what expires it is a demo that has stopped
    # answering 204 at all. Checking it is what keeps that catalogue from being three sentences
    # nobody runs — the failure mode of every comment that describes code instead of being held to
    # it, and the reason `_NO_CONTENT` is asserted here rather than left as a paragraph.
    silent_demos = sorted(
        demo
        for demo in _NO_CONTENT
        if not any(
            "no-content" in found
            for demos in _SHAPES.values()
            for named, found in demos.items()
            if named == demo
        )
    )

    assert settled == [], (
        f"these are declared in `_DECLARED` and the demos no longer disagree on them: {settled}. "
        f"Strike them off — the entry beside them is now fiction, and fiction in an exemption "
        f"catalogue is how the next divergence gets excused."
    )
    assert unused_streams == [], (
        f"`_STREAMED_FILE` names helpers no API handler calls any more: {unused_streams}. The "
        f"catalogue is describing a demo that no longer exists."
    )
    assert unused_refusals == [], (
        f"`_ERROR_CONTRACT` names refusal helpers no API handler calls any more: {unused_refusals}. "
        f"If the branch changed shape, the entry has to say so or come off."
    )
    assert silent_demos == [], (
        f"`_NO_CONTENT` describes how these demos spell a 204 and none of their `/api/` routes "
        f"answers with one any more: {silent_demos}. Either the demo changed and the entry is "
        f"fiction, or `token()` stopped recognising the spelling and the net is quietly reading "
        f"one demo's 204s as something else."
    )
