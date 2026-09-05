"""The ORM packages do not import each other in a circle, and that gets checked instead of trusted.

A cycle does not break anything by itself: Python tolerates it if somebody moves the import inside a
function, which is exactly what was there. The problem is what it HIDES. A lazy import is a
dependency you cannot see in the file header, and this project already paid for an import-order bug
—a foreign key pointing at the table of another model with the same name, right about half the time
depending on the order in which the modules got loaded—.

Before this test there was **one** real cycle (`decorators <-> query`) and twenty-eight imports
inside functions. Out of those twenty-eight, only two were genuinely necessary: the rest was caution
inherited from the one that was, copied from file to file without anyone checking again whether it
was still needed.

It is measured by PACKAGE and not by module on purpose: a cycle between `a.x` and `a.y` is an
internal detail that is sometimes the natural way to express something. One between `query` and
`decorators` is a misplaced layer, and those are the expensive ones.
"""

from __future__ import annotations

import ast
import collections
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent / "snakeorm"


def _package_graph() -> dict[str, set[str]]:
    """Which `snakeorm` package imports which, reading the REAL imports of every file.

    It also counts the imports inside functions: a cycle hidden in a body is still a cycle, and
    keeping it out of the graph would be exactly the self-deception this test exists to prevent.
    """
    graph: dict[str, set[str]] = collections.defaultdict(set)
    for path in _ROOT.rglob("*.py"):
        relative = path.relative_to(_ROOT)
        package = relative.parts[0] if len(relative.parts) > 1 else "raiz"
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "snakeorm."
            ):
                target = node.module.split(".")[1]  # type: ignore[union-attr]
                if target != package:
                    graph[package].add(target)
    return graph


def test_there_are_packages_to_check() -> None:
    """The net is useless with no fish: if the graph comes out empty, this file measures nothing."""
    graph = _package_graph()

    assert len(graph) >= 8, f"only {len(graph)} packages with dependencies were found"


def test_no_two_packages_import_each_other() -> None:
    """No pair of packages imports one another. Zero, and it stays at zero.

    The one that existed —`decorators <-> query`— was caused by ONE one-line predicate
    (`is_abstract`) that `query` needed in order to give a useful error. Its module was a leaf, but
    the `__init__` of its package drags in `view.py`, which imports `query`. A package import brings
    the whole package along, and that is where these cycles form without anyone writing them on
    purpose.
    """
    graph = _package_graph()
    cycles = {
        frozenset((origin, target))
        for origin, targets in graph.items()
        for target in targets
        if origin in graph.get(target, set())
    }

    assert cycles == set(), (
        "these packages import each other in a circle: "
        + "; ".join(" <-> ".join(sorted(pair)) for pair in sorted(cycles, key=sorted))
        + ". A cycle gets papered over with an import inside a function, and then the dependency "
        "stops being visible in the file's header."
    )


def test_lazy_imports_stay_rare() -> None:
    """Imports inside functions are the exception, not the house style.

    They are not forbidden: two legitimate ones remain —`query` imports `joined` from the inside
    because `joined` needs `SnakeQuery` at RUNTIME, and that one really is a cycle you cannot reduce
    without splitting a module—. What is watched is that they do not proliferate again: they got to
    twenty-eight, of which twenty-six were unnecessary, because nobody went back to check whether
    the cycle that justified them still existed.
    """
    per_file = {
        path.relative_to(_ROOT).as_posix(): sum(
            1
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for child in ast.walk(node)
            if isinstance(child, ast.ImportFrom)
            and (child.module or "").startswith("snakeorm")
        )
        for path in _ROOT.rglob("*.py")
    }
    excessive = {f: n for f, n in per_file.items() if n > 3}

    assert excessive == {}, (
        f"files with too many lazy imports: {excessive}. Each one hides a dependency; if they "
        f"really are needed, the cycle that justifies them deserves fixing."
    )


def test_a_lazy_import_never_names_a_module_the_file_already_imports() -> None:
    """An import inside a function, of a module that is ALREADY in the header, dodges nothing.

    The threshold above watches how MANY there are; this watches whether each one can possibly be
    doing its job. A lazy import exists to break a cycle — and there is no cycle to break with a
    module the file has already imported at the top: by the time the function runs, it is loaded.

    It is the sharper question of the two, and the count could not ask it. `asyncsession.py` sat at
    exactly three, one under the ceiling, and all three named `session.py`, which its own header
    imports twelve symbols from. One of them ran on EVERY `AsyncSession()`.
    """
    offenders: dict[str, list[str]] = {}
    for path in _ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        header = {
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
        }
        inside = [
            child.module
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for child in ast.walk(node)
            if isinstance(child, ast.ImportFrom)
            and (child.module or "").startswith("snakeorm")
            and child.module in header
        ]
        if inside:
            offenders[path.relative_to(_ROOT).as_posix()] = sorted(set(inside))

    assert offenders == {}, (
        f"these lazy imports name a module their own file already imports, so they break no cycle "
        f"and only hide the dependency: {offenders}"
    )
