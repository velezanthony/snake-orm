"""How a `python_type` off the compiled graph is SPELLED in generated Python source.

Two generators write annotations from the same metadata — the DB-first scaffolder
(`introspection/models.py`) and the DTO generator (`dto/`) — and they have to spell a type the same
way or the mirror and the DTO of one column would disagree about what it is. That is why this lives
here and not inside either of them: one question, one answer.
"""

from __future__ import annotations

import snakeorm

PARAMETERISED: dict[type, str] = {
    dict: "dict[str, object]",
    list: "list[object]",
}
"""How the generic builtins are SPELLED in generated code.

`object` and not `Any`: the value really is unknown, and `object` says so while still making the
checker ask for a narrowing before use. `Any` would say the opposite — that anything goes — which is
what the bare form silently meant.
"""

FROM_SNAKEORM = "<snakeorm>"
"""Marks "this symbol goes in the `from snakeorm import ...`", not in an `import` of its own."""


def type_annotation(python_type: type) -> tuple[str, str | None]:
    """The type's name exactly as it is written in the annotation, and its import if one is needed.

    A type from the ORM ITSELF (`SnakeUtc`) is written bare and comes in through the
    `from snakeorm import` the file already has: rendering it as `snakeorm.times.SnakeUtc` with its
    own separate import would be exposing an internal path in a file people read, and tying it to
    never moving again.
    """
    if python_type.__module__ == "builtins":
        # `dict` and `list` are written PARAMETERISED. A bare `dict` is `dict[Any, Any]`, so every
        # read through it comes back `Any` and the code this ORM generates would hand the user the
        # one thing the project forbids — in a file it wrote itself. The decision lives here and not
        # in the caller because this is the function that decides how a type is spelled.
        parameterised = PARAMETERISED.get(python_type)
        if parameterised is not None:
            return parameterised, None
        return python_type.__qualname__, None
    if getattr(snakeorm, python_type.__qualname__, None) is python_type:
        return python_type.__qualname__, FROM_SNAKEORM
    return (
        f"{python_type.__module__}.{python_type.__qualname__}",
        python_type.__module__,
    )
