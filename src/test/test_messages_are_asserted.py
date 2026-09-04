"""A `pytest.raises` on one of the ORM's OWN exceptions checks WHAT it said, not just that it blew up.

The doctrine of this project is that the ORM shouts and never fixes things behind your back, which
makes the message the PRODUCT — the whole value of `SnakeUnknownColumn` over a bare `KeyError` is
the sentence it carries. And eighty-six `pytest.raises` did not look at that sentence at all, so the
wording could be emptied out and the suite would stay green over it.

WHAT IS AND IS NOT DEMANDED, and the line matters more than the rule. Only the exceptions this
project WRITES are covered. `TypeError` from a missing argument, `FrozenInstanceError` from a frozen
dataclass and `ValueError` from the standard library carry Python's words, not ours: pinning those
would be pinning somebody else's text, and it would break on a Python upgrade for no reason at all.

AND A WARNING ABOUT THE CURE. `match=` accepts anything, so it is very easy to satisfy this net with
a fragment that proves nothing: this repository already carries `match="of"` (two letters that
appear in almost any English sentence), `match="5"` and `match="0.3"` — where the dot is a wildcard.
A bad `match` is WORSE than none, because it looks like the message is checked. If a case is
genuinely about the class and not the words, exempt it here with the reason written down; do not
invent a substring that passes.
"""

from __future__ import annotations

import ast
import pathlib


_ROOT = pathlib.Path(__file__).resolve().parent

_EXEMPT: dict[str, str] = {}
"""`file:line -> why` for raises on an ORM exception that deliberately do not check the message.

Empty for now, and that is the point: an entry here is a decision somebody wrote down, not a
backlog. Adding one costs a sentence explaining why the class alone is the whole assertion.
"""


def _ours(expression: str) -> bool:
    """Is the expected exception one this project writes?

    By NAME and not by import: the test files spell it however they spell it, and every exception in
    this ORM is prefixed. That prefix is the convention `test_public_api` already leans on.
    """
    return "Snake" in expression


def _checks_the_message(item: ast.withitem) -> bool:
    """Does this `with pytest.raises(...)` look at WHAT was said, one way or the other?

    Two ways count, and both are real. `match=` is the compact one. Binding the exception —
    `as error` — and asserting on `str(error.value)` afterwards is the other, and it is often the
    BETTER one: it can compare the whole sentence instead of a fragment, which is what
    `test_plan_sharing` does when the message itself is the object of the test.

    Only checking for `match=` was the first version of this net, and it flagged a dozen tests that
    do exactly the right thing — an assertion that cannot tell correct from incorrect, which is the
    shape this repository keeps finding in its own suite. The binding is the signal: nobody names an
    exception they are not going to read.
    """
    call = item.context_expr
    if isinstance(call, ast.Call) and any(k.arg == "match" for k in call.keywords):
        return True
    return item.optional_vars is not None


def _raises_without_match() -> list[str]:
    """`file:line -> exception` for every raise on our own exception whose message nobody reads."""
    found: list[str] = []
    for path in sorted(_ROOT.rglob("test_*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue  # this file TALKS about them
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            for item in node.items:
                call = item.context_expr
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "raises"
                    and call.args
                ):
                    continue
                expected = ast.unparse(call.args[0])
                if not _ours(expected) or _checks_the_message(item):
                    continue
                where = f"{path.relative_to(_ROOT)}:{call.lineno}"
                if where not in _EXEMPT:
                    found.append(f"{where} -> {expected}")
    return found


def test_there_are_raises_to_check() -> None:
    """There are `pytest.raises` on our exceptions at all. Without this the net measures nothing."""
    total = sum(
        1
        for path in _ROOT.rglob("test_*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "raises"
        and node.args
        and _ours(ast.unparse(node.args[0]))
    )

    assert total > 0, "nobody asserts on our exceptions, so this file is decoration"


def test_our_exceptions_are_asserted_by_what_they_say() -> None:
    """Every `pytest.raises` on a `Snake*` exception carries a `match`, or is exempt with a reason."""
    missing = _raises_without_match()

    assert missing == [], (
        f"{len(missing)} raises on this ORM's own exceptions do not look at the message, which is "
        f"the part that has any value over a bare KeyError:\n  " + "\n  ".join(missing)
    )
