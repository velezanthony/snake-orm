"""The `self: SnakeToOne[N | None]` overload must be declared FIRST, and getting it wrong is silent.

Overload resolution picks the first arm that matches. The narrow arm — the one whose `self` is
`SnakeToOne[N | None]`, which is what unwraps the `| None` so `Post.editor.username` can be written
— matches a strict subset of what the generic `self: SnakeToOne[M]` arm matches. So if the generic
one is declared above it, it wins every call and the narrow one becomes dead code.

Nothing reports that. Not mypy, not pyright, not ruff, not the runtime: the file is still valid,
every signature is still well formed, and the ORM simply goes back to the old behaviour where
navigating a nullable relation does not type-check. A reordering during an unrelated refactor —
a formatter, a merge, somebody grouping the overloads "logically" — would undo the fix and leave
no trace.

The behavioural nets in `src/test/dto/test_an_optional_to_one_navigates.py` DO catch it, and they
are the real guarantee. This test exists next to them because when it fails it says WHY in one
line, instead of leaving whoever reordered the block to work backwards from a revealed type.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from snakeorm.fields import relationship


def _overloads_of_get(class_name: str) -> list[ast.FunctionDef]:
    """The `@overload`-decorated `__get__` declarations of a class, in source order.

    Read from the AST rather than from `typing.get_overloads` because the ORDER is the whole
    subject, and the registry `get_overloads` reads is keyed for lookup, not for position.
    """
    tree = ast.parse(Path(inspect.getfile(relationship)).read_text(encoding="utf-8"))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return [
        node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "__get__"
        and any(
            isinstance(decorator, ast.Name) and decorator.id == "overload"
            for decorator in node.decorator_list
        )
    ]


def _self_annotation(node: ast.FunctionDef) -> str:
    """The source text of the `self` parameter's annotation, or `""` when it carries none."""
    annotation = node.args.args[0].annotation
    return "" if annotation is None else ast.unparse(annotation)


def test_the_optional_arm_is_the_first_overload() -> None:
    """`SnakeToOne.__get__`'s first overload is the one that narrows `self` to the optional form.

    If this fails, the fix for navigating nullable relations has been switched off without any tool
    saying so: move the `self: SnakeToOne[N | None]` arm back to the top of the block.
    """
    overloads = _overloads_of_get("SnakeToOne")

    assert len(overloads) == 3, (
        f"expected three overloads of SnakeToOne.__get__, found {len(overloads)}: the shape of "
        f"this contract changed and the order rule needs rereading"
    )
    assert _self_annotation(overloads[0]) == "SnakeToOne[N | None]", (
        "the optional-unwrapping overload must come FIRST. Declared after the generic "
        "`self: SnakeToOne[M]` arm it never matches, and navigating a nullable relation silently "
        "stops type-checking again."
    )


def test_the_generic_arm_still_follows_it() -> None:
    """The second arm is the plain one, so a required to-one keeps resolving to `type[M]`.

    Asserted because "the optional arm is first" is satisfiable by deleting the generic arm too,
    and that would take every NON-nullable relation down with it.
    """
    overloads = _overloads_of_get("SnakeToOne")

    assert _self_annotation(overloads[1]) == "SnakeToOne[M]"
    assert ast.unparse(overloads[1].returns or ast.Constant(None)) == "type[M]"


def test_the_instance_arm_is_last_and_does_not_narrow_self() -> None:
    """Instance access keeps `M` whole, `| None` included, and takes no `self` annotation.

    This is the arm that makes the change CORRECT rather than merely convenient: `post.editor` has
    to stay `FlatAuthor | None`. Narrowing `self` here as well would unwrap the `None` off the value
    a caller reads off a real row, which is a type lie the ORM does not allow itself.
    """
    overloads = _overloads_of_get("SnakeToOne")

    assert _self_annotation(overloads[2]) == "", (
        "the instance overload must not narrow `self`, or the value read off a row would lose "
        "its `None`"
    )
    assert ast.unparse(overloads[2].returns or ast.Constant(None)) == "M"
