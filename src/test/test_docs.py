"""Documentation cannot promise an API that does not exist.

It is the silent failure every set of docs has: nothing blows up, nothing shows in a test, and the
only person who finds out is whoever copies the example and watches it not work. By then they have
lost the afternoon and the trust.

Three things are checked here, and all three are mechanical on purpose — nobody eyeballs twenty
files twice:

1. Every ```python block in the docs is **syntactically valid** Python. An example that does not
   even parse is the first thing to slip in when a section gets rewritten.
2. Every name imported from `snakeorm` in the docs **genuinely exists** in the public API. This is
   the one that catches the expensive mistake: documenting `snake_column(nullable=True)` years after
   it was removed, or a `session.query()` that never existed at all.
3. Every model the docs declare **compiles**. The first two look at the TEXT, and there is a whole
   family of lies the text does not give away: `snake_column()` over a `datetime` imports a name
   that exists, parses perfectly, and is a compiler error. It actually happened — when dates were
   split into `snake_datetime`/`snake_datetimetz`, six pages were left teaching code that blows up
   and the two tests stayed green. Same lesson already written down in
   `test/introspection/test_scaffold_compiles.py`: to know whether something works, you have to call it.

A block that declares a model IS run whole, top to bottom, with the real decorators. It used to be
run under a broad `except Exception: pass` that forgave everything but a `SnakeError`, on the
argument that an incomplete fragment must not drag the suite into being an integration suite. The
argument was right and the mechanism was wrong: an `except` that wide cannot tell a fragment from a
broken example, and it hid twenty of the second kind across twelve pages — the guide's own
`User(email=...)` among them. What replaced it is `_NOT_EXECUTABLE`: the blocks that genuinely
cannot run, listed one by one with the reason, and everything else has to work.

Only blocks tagged ```python are looked at, and that tag is a DECLARATION: it says what is inside is
executable Python. A REPL transcript goes as ```pycon and a loose fragment or pseudocode goes as
```text — not to escape the check, but because tagging as `python` something that is not one is
already a documentation error in itself. The highlighting comes out better too.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import pathlib
import re
import sys
import textwrap
import types
from collections.abc import Iterator

import pytest

import snakeorm
from snakeorm.core import converters
from snakeorm.registry import registry

# docs/ lives at the ROOT of the repo, not under src/: src/test -> src -> root.
_DOCS = pathlib.Path(__file__).resolve().parent.parent.parent / "docs"
_BLOCK = re.compile(
    r"^(?P<sangria>[ \t]*)```python\n(?P<cuerpo>.*?)^(?P=sangria)```",
    re.MULTILINE | re.DOTALL,
)
"""A ```python block, INDENTED OR NOT.

It used to demand the fence at column 0, and that left out everything living inside a tab
(`=== "PostgreSQL"`), which in Markdown is indented. Which is to say: the page with the most code per
screen — installation, the first one anybody runs — was invisible to all THREE nets at once: nobody
checked that its imported names existed, that its snippets parsed, or that its models compiled.

The indentation is captured so the closing fence can be required to carry the SAME one, and so it can
be stripped from the body before parsing: an indented block is an `IndentationError` if handed to
`ast` as it is.
"""

# The planning pages are project history, not documentation: their examples describe APIs that were
# considered and sometimes never built. Excluding them is right; including them would be demanding a
# roadmap behave like a manual.
_EXCLUDED = ("planning",)


def _pages() -> list[pathlib.Path]:
    """The USER documentation pages, which are the ones making a promise."""
    return sorted(
        page
        for page in _DOCS.rglob("*.md")
        if not any(part in _EXCLUDED for part in page.parts)
    )


def _blocks(page: pathlib.Path) -> list[str]:
    """A page's Python code blocks, with their tab's indentation already stripped."""
    return [
        textwrap.dedent(found.group("cuerpo"))
        for found in _BLOCK.finditer(page.read_text())
    ]


def test_there_is_documentation_to_check() -> None:
    """A net is no use with no fish in it: with no pages, this file is lying.

    A test parametrised over an empty list passes green without checking anything, and that trap has
    already shown up on this branch with three tests that measured absolutely nothing.

    The MODELS are counted separately, and that number is the one guarding the hardest test of the
    three. It is gated by `_declares_a_model`, so a bug in the gate — or a rewrite that stops
    matching — would leave `test_every_documented_model_compiles` iterating over nothing and passing
    green over documentation nobody executes any more. Measured today: 34 blocks declare a model.
    """
    pages = _pages()

    assert len(pages) >= 10, f"only {len(pages)} pages were found in {_DOCS}"
    assert sum(len(_blocks(p)) for p in pages) >= 50, (
        "far too few examples to be a guide"
    )
    models = sum(1 for p in pages for block in _blocks(p) if _declares_a_model(block))
    assert models >= 30, (
        f"only {models} blocks declare a model: the gate of "
        f"test_every_documented_model_compiles stopped matching, and that test is now green over "
        f"nothing"
    )


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_every_python_example_parses(page: pathlib.Path) -> None:
    """Every ```python block on the page is valid Python.

    The `...` of a trimmed example are allowed — they are `Ellipsis`, legitimate syntax — because an
    example teaching one single thing is better documentation than a complete, unreadable one.
    """
    for number, block in enumerate(_blocks(page), start=1):
        try:
            ast.parse(block)
        except SyntaxError as error:
            raise AssertionError(
                f"{page.name}, block {number}: not valid Python ({error})"
            ) from error


def _missing_from_submodule(node: ast.ImportFrom) -> list[str]:
    """The names in a `from snakeorm.something import X` that the submodule does not have.

    A module that cannot be imported counts as missing IN FULL: a documented path does not exist, and
    it makes no difference whether the module or the name was the one misspelled.
    """
    assert node.module is not None
    try:
        module = importlib.import_module(node.module)
    except ImportError:
        return [f"{node.module}.{alias.name}" for alias in node.names]
    return [
        f"{node.module}.{alias.name}"
        for alias in node.names
        if not hasattr(module, alias.name)
    ]


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_every_documented_name_exists_in_the_public_api(page: pathlib.Path) -> None:
    """Every `from snakeorm import X` in the docs imports something that EXISTS.

    This is the test that really matters. A name that gets renamed or removed leaves behind
    documentation that goes on teaching it, and no test of the code catches that: the code is fine,
    it is the promise that stopped being one.

    Imports from ANY `snakeorm` module are checked, not only the root package's. It used to look at
    the root alone, on the argument that the submodules were already covered by "the example's real
    import" — but nothing here executes that import, so nobody covered them. And they are exactly the
    ones the internals are documented with (`snakeorm.dialects.capabilities`, `snakeorm.migration`),
    which is the part that moves most.
    """
    # The facade re-exports with `X as X` and no `__all__`: the public surface is its attributes
    # without a leading underscore that are not submodules (submodules import themselves).
    public_names = {
        name
        for name, value in vars(snakeorm).items()
        if not name.startswith("_") and not isinstance(value, types.ModuleType)
    }
    missing: list[str] = []
    for block in _blocks(page):
        try:
            tree = ast.parse(block)
        except SyntaxError:
            continue  # the previous test already reports it; the failure is not duplicated here
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if node.module == "snakeorm":
                missing.extend(
                    alias.name for alias in node.names if alias.name not in public_names
                )
            elif node.module.startswith("snakeorm."):
                missing.extend(_missing_from_submodule(node))

    assert missing == [], (
        f"{page.name} documents names that do not exist: {sorted(set(missing))}"
    )


@contextlib.contextmanager
def _disposable_registry() -> Iterator[None]:
    """An EMPTY registry for the duration of the block, and the previous one back on the way out.

    Registering is needed: `snake_check()`, `snake_index()` and company look the model up IN the
    registry and raise if it is not there, so a model that merely compiled would declare perfectly
    good documentation broken.

    The CONVERTER registry travels with it, and it is not the same registry — it is the other axis of
    the type vocabulary, in `core/converters.py`, and it is a process-wide singleton too. The column
    guide teaches `register_converter` with an example that runs here, so every run of this file was
    leaving an `Inet` behind in the global table: a class that only exists inside one `exec`, sitting
    in a registry the whole suite reads from. Nothing broke, which is exactly why it would have gone
    on doing it.

    Emptying it first is needed just as much, for two different reasons. Outside in: the registry is a
    process singleton, so the guide's `users` collided with the `User` of any other test module
    that had run first — a failure that only appeared in the full suite and vanished when the file ran
    alone, one of the worst kinds to diagnose. Inside out: `table="orders"` appears on several pages,
    and whatever was left inside would be eaten by the rest.

    So each block runs in a world of its own, which is exactly what it is: a loose example from a page,
    not a neighbour of the rest of the repository.

    It is saved and restored through the `__dict__` rather than naming the stores one by one on
    purpose: a new store somebody adds to the registry is covered here by itself, without this test
    looking the other way and without anyone finding out.
    """
    previous = {name: value.copy() for name, value in vars(registry).items()}
    to_db = converters._TO_DB.copy()
    from_db = converters._FROM_DB.copy()
    for store in vars(registry).values():
        store.clear()
    try:
        yield
    finally:
        vars(registry).update(previous)
        converters._TO_DB.clear()
        converters._TO_DB.update(to_db)
        converters._FROM_DB.clear()
        converters._FROM_DB.update(from_db)


@contextlib.contextmanager
def _example_module(page: pathlib.Path, number: int) -> Iterator[types.ModuleType]:
    """A REAL, throwaway module carrying the public API, registered in `sys.modules`.

    A real module and not a plain `dict`, and that is the whole point rather than a detail. A class
    born inside an `exec` over a loose dictionary belongs to no module, so `get_type_hints()` — which
    the compiler calls to read the annotations — has nowhere to resolve names against and every
    single one comes back `NameError`. Two families of examples died of exactly that and the broad
    `except` buried both: the ones opening with `from __future__ import annotations` (PEP 563 turns
    every annotation into a string that then has to be resolved), and the ones declaring a
    relationship by forward reference (`SnakeToMany["Brand"]`, with `Brand` further down the block).
    Both work perfectly for a user who pastes them into a file of their own, which is what makes the
    failure a fault of the harness and not of the documentation.

    The decorators are the REAL ones, with no doubles in between. The doubles existed to keep the
    registry clean, and `_disposable_registry` already does that on its own; what they did instead
    was lie, because a double is a second implementation and it drifted from the first: it built no
    `__init__` (so `User(email=...)`, the very line the guide teaches, blew up with `TypeError`) and
    it forwarded `discriminator_value=` straight to `compile_model`, which does not take it. Two
    green pages over broken examples.

    Submodules are left OUT of the environment for the same reason `test_every_documented_name_...`
    leaves them out of the public surface: `snakeorm.session` injected under the name `session`
    turns an undefined variable in an example into an `AttributeError` against a module, which hides
    what is really going on.
    """
    name = f"snakeorm_doc_example_{page.stem.replace('.', '_')}_{number}"
    module = types.ModuleType(name)
    module.__dict__.update(
        {
            n: v
            for n, v in vars(snakeorm).items()
            if not n.startswith("_") and not isinstance(v, types.ModuleType)
        }
    )
    sys.modules[name] = module
    try:
        yield module
    finally:
        del sys.modules[name]


def _without_package_imports(block: str) -> str:
    """The block with its `from snakeorm import ...` taken out, one line or several.

    Left in, the real import would trample the environment's doubles and the example would register
    for real. No names are lost: the environment already carries them all. SUBMODULE imports
    (`snakeorm.metadata`) stay — they bring no decorators and are part of what is checked.
    """
    lines = block.split("\n")
    for node in ast.walk(ast.parse(block)):
        if isinstance(node, ast.ImportFrom) and node.module == "snakeorm":
            for index in range(node.lineno - 1, node.end_lineno or node.lineno):
                lines[index] = ""
    return "\n".join(lines)


def _declares_a_model(block: str) -> bool:
    """Whether the block declares a MODEL: a class annotating at least one `SnakeColumn[...]`.

    The gate used to be the substring `SnakeColumn[` anywhere in the block, and being textual it
    could not tell a model from a mention of one. It swept in four loose fragments of the column
    guide — bare `price: SnakeColumn[Decimal] = snake_decimal(...)` lines, with no class around them
    and no import of `Decimal` — which a reader understands at a glance and `exec` cannot run at all.
    Reading the tree instead of the text, they are what they are: not models, so nothing to compile,
    so no exemption to write down for them either.
    """
    try:
        tree = ast.parse(block)
    except SyntaxError:
        return False  # `test_every_python_example_parses` reports it; not repeated here
    return any(
        isinstance(node, ast.ClassDef)
        and any(
            isinstance(body, ast.AnnAssign)
            and "SnakeColumn[" in ast.unparse(body.annotation)
            for body in node.body
        )
        for node in ast.walk(tree)
    )


def _canonical(page: pathlib.Path) -> str:
    """The page's path under `docs/`, with the language suffix dropped: `users/guide/columns.md`.

    The two translations of a page carry the SAME code blocks in the SAME order —
    `test_docs_share_one_code.py` is the net that guarantees it — so an example that cannot be
    executed cannot be executed in either language. One entry covers the pair; two would be the same
    fact written twice, and the day they disagreed one of them would be a lie.
    """
    return page.relative_to(_DOCS).as_posix().replace(".es.md", ".md")


_NOT_EXECUTABLE: dict[tuple[str, int], str] = {
    ("index.md", 2): (
        "the tour ends by OPENING a session against a real database: it names a `dsn` that the "
        "reader supplies. Standing a server up here is exactly the integration suite this module "
        "refuses to become — and the models above the session do compile, which is the part checked"
    ),
    ("users/engines/multi-connection.md", 3): (
        "a fragment showing the DEFAULT connection next to the one before it: its `Event` is "
        "declared in that other block, on the `analytics` database, which is the whole point being "
        "made. Pasting the two together to make it run would destroy what the example teaches"
    ),
}
"""The model blocks that CANNOT be executed whole, one by one and each with its reason.

This is the replacement for a bare `except Exception: pass`, and the difference is not cosmetic. The
`except` was a blanket permit: it forgave the two blocks below and, with them, eighteen others that
were simply broken — a `TypeError` from the harness's own doubles, a `NameError` from a module that
did not exist. The test could not fail, so its name was a promise it had no way of keeping.

A written-down list has the property the `except` lacked: it is FINITE and it is checked. Anything
outside it fails, and anything inside it that starts working fails too — see
`test_no_exemption_outlives_its_reason`. The same doctrine as `_NOT_YET` and `_OUT_OF_SCOPE` in
`frameworks/shared/tests/`: what is not verified gets DECLARED, never hidden.
"""


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_every_documented_model_compiles(page: pathlib.Path) -> None:
    """Every model the page declares is EXECUTED, and only a declared block is allowed not to run.

    Any exception fails the test, not just `SnakeError`. It used to judge the ORM's own complaint
    alone and swallow the rest as "an incomplete fragment", and that branch is where the interesting
    failures lived: a `TypeError` from a guide example calling the constructor it teaches, a
    `NameError` from every annotation of every block that opened with `from __future__ import
    annotations`. Twenty of them, on twelve pages, under a green test.

    `dont_inherit=True` is NOT decorative: `compile()` inherits the caller's `__future__` flags by
    default and this module has `from __future__ import annotations`. Without it every example is
    compiled under PEP 563 whether it asked for it or not.
    """
    unexpected: list[str] = []
    ran: set[int] = set()
    for number, block in enumerate(_blocks(page), start=1):
        if not _declares_a_model(block):
            continue
        code = compile(
            _without_package_imports(block),
            f"<{page.name}:{number}>",
            "exec",
            dont_inherit=True,
        )
        try:
            with _disposable_registry(), _example_module(page, number) as module:
                exec(code, module.__dict__)  # noqa: S102
        except Exception as error:  # noqa: BLE001
            if (_canonical(page), number) in _NOT_EXECUTABLE:
                continue
            unexpected.append(f"block {number}: {type(error).__name__}: {error}")
        else:
            ran.add(number)

    assert unexpected == [], (
        f"{page.name} documents models that do not run:\n"
        + "\n".join(unexpected)
        + f"\n\nIf the block genuinely cannot be executed, declare it in _NOT_EXECUTABLE with its "
        f"reason, keyed by ('{_canonical(page)}', <number>). Do not widen an `except`."
    )
    stale = sorted(
        number
        for (canonical, number) in _NOT_EXECUTABLE
        if canonical == _canonical(page) and number in ran
    )
    assert stale == [], (
        f"{page.name}: blocks {stale} are declared in _NOT_EXECUTABLE and DO run now. "
        f"An exemption that outlived its reason hides the next failure: take it off the list."
    )


def test_no_exemption_outlives_its_reason() -> None:
    """Every entry in `_NOT_EXECUTABLE` names a block that exists and carries a reason worth reading.

    A list of exemptions rots the moment a page is rewritten and its blocks renumber: the entry stops
    pointing at anything, goes on looking like diligence, and forgives a block nobody chose to
    forgive. That is the failure mode of every allow-list, and it is why this one is checked rather
    than trusted.

    Whether a declared block still FAILS is the other half, and it is checked where the blocks are
    actually executed — in `test_every_documented_model_compiles`, page by page.
    """
    blocks_by_page: dict[str, int] = {}
    for page in _pages():
        blocks_by_page[_canonical(page)] = sum(
            1 for block in _blocks(page) if _declares_a_model(block)
        )

    for (canonical, number), reason in _NOT_EXECUTABLE.items():
        assert canonical in blocks_by_page, (
            f"_NOT_EXECUTABLE names {canonical}, which is not a documentation page"
        )
        assert 1 <= number <= len(_blocks(_DOCS / canonical)), (
            f"_NOT_EXECUTABLE names block {number} of {canonical}, which has no such block"
        )
        assert len(reason) >= 40, (
            f"the exemption for {canonical}:{number} says '{reason}': a reason has to explain WHY "
            f"the block cannot run, or the list is an `except Exception` with extra steps"
        )
