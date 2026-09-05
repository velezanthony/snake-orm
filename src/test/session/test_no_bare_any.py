"""No BARE `Any` annotation survives in `session/` or `expressions/`.

`uv run mypy --strict src/snakeorm` is the project's type gate and it does NOT include
`disallow_any_explicit`: an `Any` written by hand crosses it untouched. In a project whose headline
rule is ZERO `Any`, that is the gate measuring `Any` and reporting Success. This test closes the
hole for the two packages it belongs to.

WHAT IT CHECKS, exactly, so the name can be honoured: it parses each module and reports every
annotation that IS the bare name `Any` — a parameter, a return, or an annotated assignment. It is an
AST sweep, not a word list: it cannot miss a spelling, because it reads the annotation the checker
reads.

WHAT IT DOES NOT CHECK: `X[Any]` (`SnakeValue[Any]`, `dict[str, Any]`, `type[Any]`). That is a
different statement — a generic whose parameter is unknown, which is what those doors genuinely take
— and folding the two together would turn this into a test nobody can keep green.

WHY THESE TWO PACKAGES AND NOT THE TREE: sweeping the whole package is `disallow_any_explicit` by
another name, and turning that on surfaces debt across nineteen subpackages that this change
deliberately does not touch. The roots are read off the two packages this net owns, and the sweep
inside them is exhaustive.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import snakeorm

_PACKAGE = Path(snakeorm.__file__).parent
_SWEPT_PACKAGES = ("session", "expressions")


def _is_bare_any(node: ast.expr | None) -> bool:
    """Is this annotation the bare `Any` (however it is spelled)?

    Three spellings reach the same type: `Any`, `typing.Any` and the quoted `"Any"`. A subscript
    (`SnakeValue[Any]`) is NOT one of them: the annotation there is the generic, not `Any`.
    """
    if isinstance(node, ast.Name):
        return node.id == "Any"
    if isinstance(node, ast.Attribute):
        return node.attr == "Any"
    if isinstance(node, ast.Constant):
        return node.value == "Any"
    return False


class _BareAnySweep(ast.NodeVisitor):
    """Collects every bare-`Any` annotation with the path that names it (`Class::function::arg`)."""

    def __init__(self) -> None:
        self.found: list[str] = []
        self._scope: list[str] = []

    def _record(self, what: str, annotation: ast.expr | None) -> None:
        """Notes the annotation if it is a bare `Any`, named by its enclosing scope."""
        if _is_bare_any(annotation):
            self.found.append("::".join([*self._scope, what]))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Walks into the class carrying its name, so the report says which one."""
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """A synchronous function: its arguments and its return."""
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """An asynchronous one, which is the half where the drift lives."""
        self._function(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """An annotated assignment: a dataclass field or a local variable."""
        target = node.target
        name = target.id if isinstance(target, ast.Name) else ast.unparse(target)
        self._record(name, node.annotation)
        self.generic_visit(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Every argument (positional, keyword, `*args`, `**kwargs`) plus the return type."""
        self._scope.append(node.name)
        arguments = node.args
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            arguments.vararg,
            arguments.kwarg,
        ):
            if argument is not None:
                self._record(argument.arg, argument.annotation)
        self._record("return", node.returns)
        self.generic_visit(node)
        self._scope.pop()


def bare_any_annotations(source: str) -> list[str]:
    """Every bare-`Any` annotation in the source, named by scope. Empty means clean."""
    sweep = _BareAnySweep()
    sweep.visit(ast.parse(source))
    return sweep.found


_MODULES = sorted(
    module
    for package in _SWEPT_PACKAGES
    for module in (_PACKAGE / package).rglob("*.py")
)


def test_the_sweep_has_something_to_sweep() -> None:
    """The two packages resolve to real modules: an empty sweep would pass by vacancy."""
    assert len(_MODULES) > 5


def test_the_sweep_can_fire() -> None:
    """Fed a bare `Any` it reports it; fed a parameterised one it stays quiet.

    A net that cannot fire is worse than no net, because it manufactures confidence. This pins down
    that the detector separates the two cases the docstring above promises to separate.
    """
    source = (
        "class Holder:\n"
        "    def leaks(self, hop: Any, other: typing.Any) -> Any:\n"
        "        found: Any = 1\n"
        "        return found\n"
        "    def clean(self, value: SnakeValue[Any]) -> list[Any]:\n"
        "        return []\n"
    )
    assert bare_any_annotations(source) == [
        "Holder::leaks::hop",
        "Holder::leaks::other",
        "Holder::leaks::return",
        "Holder::leaks::found",
    ]


@pytest.mark.parametrize(
    "module", _MODULES, ids=lambda path: str(path.relative_to(_PACKAGE))
)
def test_no_bare_any_annotation(module: Path) -> None:
    """This module annotates nothing as the bare `Any`.

    Parameterised per module on purpose: the failure names the file to fix instead of dumping a list
    that somebody has to bisect.
    """
    leaks = bare_any_annotations(module.read_text(encoding="utf-8"))
    assert leaks == [], (
        f"{module.relative_to(_PACKAGE)} annotates {leaks} as the bare `Any`. The strict gate does "
        f"not include `disallow_any_explicit`, so these cross it in silence. Give each one the type "
        f"it actually takes; if it genuinely takes an unknown parameter, say `X[Any]` instead."
    )
