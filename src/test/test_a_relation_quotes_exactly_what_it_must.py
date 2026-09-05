"""A relationship quotes the model it names when —and only when— that name is not bound yet.

The rule is one sentence, and what makes it testable rather than a matter of taste is that it is an
EQUALITY between two facts sitting in the same file: where the name comes from, and whether the
annotation carries quotes. That is the line this repository draws — an existence and an equality are
checked, a preference is not.

FOUR situations, and the answer is different in each:

    the name is imported at RUNTIME          ->  bare. Quotes say nothing.
    the name is a class CLOSED above          ->  bare. It is bound by then.
    the name is the class BEING DEFINED       ->  quoted. Inside its own body it is not bound yet.
    the name is imported only under the block ->  quoted. It is nowhere at runtime.

The last two are the ones that can break, and only one of them breaks today: a self-reference or a
type-checking-only import written bare survives on `from __future__ import annotations`, which
stores annotations as strings and never evaluates them. Delete that line and the class body raises
`NameError` on import — measured. So half of this file is a tripwire under a line nobody thinks
about, and the other half is about noise that reads like information: somebody comparing two lines
of one file looks for the difference that justifies the quotes, and there is none.

WHAT IS NOT CHECKED, deliberately: quoting the whole expression (`"SnakeToMany[Post]"`). It is
pointless — `SnakeToMany` comes from the ORM and can never sit in an application's import cycle —
but mypy reads inside the string (`Name "SnkToMany" is not defined`) and so does the runtime, both
measured. A rule that adds no safety belongs in a style guide, not in a test.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
_ROOTS = ("src/snakeorm", "src/test", "src/examples", "src/benchmarks", "frameworks")

_BARE_ON_PURPOSE = (
    "src/test/linker/circular_modules",
    "src/test/linker/circular_stress",
)
"""The fixtures that write a type-checking-only name BARE, because that is what they measure.

They exist to prove the linker resolves the unquoted form by reading the block, so applying the
convention to them would delete the thing under test. The exemption is by DIRECTORY and names both
packages one by one: an exemption that covers more than it must is an exemption that hides, and this
repository has the note about `debug/channel.py` for exactly that.
"""


def _files() -> list[pathlib.Path]:
    """Every Python file under the four source roots. The whole tree, never a curated list."""
    found: list[pathlib.Path] = []
    for root in _ROOTS:
        for path in (_REPO / root).rglob("*.py"):
            text = str(path)
            if "__pycache__" in text:
                continue
            found.append(path)
    return sorted(found)


def _relation_annotations(tree: ast.Module) -> list[tuple[int, ast.expr]]:
    """Every `SnakeToOne[...]`/`SnakeToMany[...]` annotation, as line and the expression inside."""
    found: list[tuple[int, ast.expr]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign) or not isinstance(
            node.annotation, ast.Subscript
        ):
            continue
        outer = node.annotation.value
        if not isinstance(outer, ast.Name) or not outer.id.startswith("SnakeTo"):
            continue
        found.append((node.lineno, node.annotation.slice))
    return found


def _named(inner: ast.expr) -> tuple[str, bool] | None:
    """The model an annotation names and whether it is quoted, or `None` if the shape is unknown.

    `None` means "this reader does not understand what was written", and it is deliberately NOT the
    same answer as "there is nothing wrong here". Both agents who rebuilt this rule under a
    different descriptor signature hit that difference: with two type parameters the slice arrives
    as an `ast.Tuple`, which had no arm — and the reader did not fail, it went QUIET, reporting
    success over declarations it never looked at. A reader that skips what it cannot parse gives the
    same answer as a clean file, which is the one answer that must never be a guess here.
    """
    if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
        # `"Brand | None"` names Brand: the optional half is not what is being resolved.
        return inner.value.split("|")[0].strip(), True
    if isinstance(inner, ast.Name):
        return inner.id, False
    if isinstance(inner, ast.BinOp):
        # `A | B | None` nests to the LEFT, so the first model is the leftmost leaf. Recursing
        # rather than reading `.left` once is what tells a two-model union apart from an unknown
        # shape: the linker refuses that union, but this reader still has to be able to SAY so.
        return _named(inner.left)
    return None


def _relations(tree: ast.Module) -> list[tuple[int, str, bool]]:
    """Every `SnakeToOne[...]`/`SnakeToMany[...]`: line, the model named, whether it is quoted."""
    return [
        (line, *named)
        for line, inner in _relation_annotations(tree)
        if (named := _named(inner)) is not None
    ]


def _bindings(
    tree: ast.Module,
) -> tuple[set[str], set[str], dict[str, tuple[int, int]]]:
    """What the file binds: names imported at runtime, names under the block, and its own classes."""
    runtime: set[str] = set()
    type_checking: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            runtime |= {alias.asname or alias.name for alias in node.names}
        if isinstance(node, ast.If):
            for sub in ast.walk(node):
                if isinstance(sub, ast.ImportFrom):
                    type_checking |= {alias.asname or alias.name for alias in sub.names}
    classes = {
        node.name: (node.lineno, node.end_lineno or node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }
    return runtime, type_checking, classes


def _offences(path: pathlib.Path) -> list[str]:
    """Every relationship in one file whose quoting disagrees with where its name comes from."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (
        SyntaxError
    ):  # pragma: no cover - a file that does not parse is another test's problem
        return []
    runtime, type_checking, classes = _bindings(tree)
    exempt = any(part in str(path) for part in _BARE_ON_PURPOSE)
    found: list[str] = []
    for line, name, quoted in _relations(tree):
        span = classes.get(name)
        if span is not None and span[0] <= line <= span[1]:
            continue  # a self-reference: quoted or bare, both are defensible inside one's own body
        if quoted and span is not None and span[1] < line:
            found.append(
                f"L{line}: {name!r} is a class closed on L{span[1]}, so it is already bound"
            )
        elif quoted and name in runtime:
            found.append(
                f"L{line}: {name!r} is imported at runtime, so the quotes say nothing"
            )
        elif not quoted and name in type_checking and not exempt:
            found.append(
                f'L{line}: {name!r} only exists under `if TYPE_CHECKING:`, so it is "{name}"'
            )
    return found


@pytest.mark.parametrize("path", _files(), ids=lambda p: str(p.relative_to(_REPO)))
def test_a_relation_quotes_exactly_what_it_must(path: pathlib.Path) -> None:
    """Parametrised per FILE so a failure names the file to edit instead of printing a list."""
    offences = _offences(path)

    assert not offences, f"{path.relative_to(_REPO)}\n  " + "\n  ".join(offences)


def test_every_situation_the_rule_covers_actually_occurs() -> None:
    """The premise. A rule nothing exercises reads exactly like a rule everybody follows.

    Each of the four situations has to be present somewhere in the tree, or the assertion above is
    passing over an empty list for a case that has quietly disappeared — the vacuous-run shape this
    repository keeps finding. The type-checking-only BARE case counts the exempt fixtures on
    purpose: they are the only place it is written, and they are what proves the rule is a
    convention rather than a correctness requirement.
    """
    seen: dict[str, int] = {
        "runtime bare": 0,
        "closed class bare": 0,
        "self reference": 0,
        "type-checking quoted": 0,
        "type-checking bare": 0,
    }
    for path in _files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        runtime, type_checking, classes = _bindings(tree)
        for line, name, quoted in _relations(tree):
            span = classes.get(name)
            if span is not None and span[0] <= line <= span[1]:
                seen["self reference"] += 1
            elif span is not None and not quoted:
                seen["closed class bare"] += 1
            elif name in type_checking:
                seen["type-checking quoted" if quoted else "type-checking bare"] += 1
            elif name in runtime and not quoted:
                seen["runtime bare"] += 1

    missing = [situation for situation, count in seen.items() if count == 0]
    assert not missing, f"no example left in the tree of: {missing}. Counted: {seen}"


@pytest.mark.parametrize("path", _files(), ids=lambda p: str(p.relative_to(_REPO)))
def test_every_relation_annotation_is_understood(path: pathlib.Path) -> None:
    """No relationship annotation is silently skipped by the reader above.

    This is the half that makes the rest of the file mean anything. `_named` returns `None` for a
    shape it does not recognise, and without this test that `None` reads exactly like "nothing wrong
    here": the file reports success over declarations it never looked at. Measured, not imagined —
    two rebuilds of this rule under a different descriptor signature both hit it, because a second
    type parameter turns the slice into an `ast.Tuple` and there was no arm for one.

    So the day `SnakeToOne` grows a shape this reader cannot parse, the answer is a red test naming
    the file and the line, and not a quiet green over an unchecked sweep.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (
        SyntaxError
    ):  # pragma: no cover - a file that does not parse is another test's problem
        return

    unknown = [
        f"L{line}: {ast.unparse(inner)!r} is a shape this reader has no arm for"
        for line, inner in _relation_annotations(tree)
        if _named(inner) is None
    ]

    assert not unknown, f"{path.relative_to(_REPO)}\n  " + "\n  ".join(unknown)
