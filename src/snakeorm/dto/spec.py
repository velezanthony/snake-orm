"""`snake_dto(...)`: the DECLARATION of a typed DTO. The class it describes is written by the CLI.

This module does one job and stops: it turns a line somebody wrote into a frozen `SnakeDtoSpec`,
refusing anything it can already tell is wrong. It never reads the graph beyond checking that the
model was compiled — resolving what a path MEANS is `resolve.py`'s job, and it needs every spec in
the file at once because a nested field points at another spec.

WHY THE FIELDS ARE DESCRIPTORS. `Post.tilte` does not compile; `"tilte"` does. That is the whole
argument, and it is measured in this package's tests against both mypy and pyright.

WHERE THE DECLARATION LIVES, and it is the decision the rest of this package hangs off: inside the
DTO file's `if TYPE_CHECKING:` block, together with the import of the models. Three properties at
once, all measured:

    mypy/pyright over `Post.tilte` inside the block  ->  error: "type[Post]" has no attribute
    importing the module at runtime                  ->  clean; nothing in the block ever runs
    importing the module at runtime                  ->  does NOT drag in `blog.models`

So the checker validates every path, the file costs nothing to import, and the import cycle between
`models.py` and `dto.py` cannot form. The generator never executes any of it: it READS the block
with `ast`. The function still works when called, but its runtime behaviour is not the product —
the type signature is.
"""

from __future__ import annotations

import keyword
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from snakeorm.core.exceptions import SnakeDtoError
from snakeorm.fields.relationship import SnakePathProxy, path_of
from snakeorm.registry import registry_of


@runtime_checkable
class SnakeDtoPath(Protocol):
    """Anything that knows the path it names: a column expression or a collection.

    Structural on purpose. `SnakeExpr` and `SnakeCollection` have nothing else in common and there
    is no shared base to name — what this function needs from both is the path, so that is what the
    type asks for. A to-one proxy deliberately does NOT match: its namespace is the target model's,
    so it cannot carry a `path` attribute without shadowing a column of that name.
    """

    @property
    def path(self) -> tuple[str, ...]: ...


SnakeDtoEntry = SnakeDtoPath | type[object]
"""One thing that can appear in `fields=`.

`type[object]` is how a to-one reads to the CHECKER: class access on `SnakeToOne[M]` is typed
`type[M]`, which is the same overload that makes `Post.author.username` resolve. It lets any class
through the type check, and that is the price of the navigation being typed at all; a class that
names no relationship is refused here, by name, at the line that wrote it.
"""

SnakeDtoSelection = SnakeDtoEntry | tuple[SnakeDtoEntry, str]
"""An entry, or an entry paired with the NAME of the DTO to nest for it.

The pair exists for one case: a model with more than one spec. `Post.author` alone cannot say
whether it means `AuthorDto` or `AuthorCard`, and picking either would be bug #14 wearing a
different hat. The disambiguation sits on the line that is ambiguous rather than in a parameter of
its own, and it stays typed.
"""


@dataclass(frozen=True, slots=True)
class SnakeDtoPick:
    """One selected field: the path it names, and the DTO to nest if the user named one."""

    path: tuple[str, ...]
    dto: str | None = None


@dataclass(frozen=True, slots=True)
class SnakeDtoSpec:
    """A declared DTO: which model, what it is called, and which of its fields are in.

    `fields` is `None` when neither switch was given, which means every column. Frozen and hashable
    like every other node this project compiles, so a spec can be a key in the dependency graph the
    renderer sorts.
    """

    model: type
    name: str
    fields: tuple[SnakeDtoPick, ...] | None = None
    exclude: tuple[tuple[str, ...], ...] = ()


def snake_dto(
    model: type,
    *,
    name: str,
    fields: list[SnakeDtoSelection] | None = None,
    exclude: list[SnakeDtoSelection] | None = None,
) -> SnakeDtoSpec:
    """Declares a DTO over `model`. Returns the spec, and records it for the generator.

    Three combinations and one refusal: neither switch means every column, `fields` means exactly
    those, `exclude` means all but those, and both together is an error because they are two answers
    to one question.

    A relationship in `fields` NESTS — `Post.author` becomes `author: AuthorDto` — and does not
    expand into the author's columns. Expanding would mean a declaration you cannot read without
    opening another model, and the point of writing the shape down is that it is a complete picture
    of what goes out.

    The spec is returned rather than recorded anywhere: in the file it is written in this line is
    never reached, so a process-wide list of declarations would be empty in production and full in
    tests.
    """
    return build_spec(
        model=model,
        name=name,
        fields=None if fields is None else tuple(_pick(item, name) for item in fields),
        exclude=None
        if exclude is None
        else tuple(_excluded(item, name) for item in exclude),
    )


def build_spec(
    *,
    model: type,
    name: str,
    fields: tuple[SnakeDtoPick, ...] | None,
    exclude: tuple[tuple[str, ...], ...] | None,
    where: str = "",
) -> SnakeDtoSpec:
    """Builds a spec out of already-normalised parts, applying the checks BOTH routes need.

    Two things produce a spec — this module's typed call, and the AST reader — and they have to
    agree about what a declaration may say. The checks live here so there is ONE answer: two copies
    would eventually differ, and the difference would be a file the generator accepts and the
    checker does not, or the other way round.

    `where` prefixes the messages with `file:line` when the caller has one. The typed call does not,
    because it fails on the line it was written on and the traceback already says which.
    """
    prefix = f"{where}: " if where else ""
    if fields is not None and exclude is not None:
        raise SnakeDtoError(
            f"{prefix}{name!r} declares both fields= and exclude=. They are two ways of answering "
            f"the same question and they can disagree: name the fields you want, or the columns "
            f"you do not, never both."
        )
    if not name.isidentifier() or keyword.iskeyword(name):
        raise SnakeDtoError(
            f"{prefix}{name!r} is not a valid class name, and this spec is written out as "
            f"`class {name}(TypedDict)`."
        )
    if registry_of(model).table_of(model) is None:
        raise SnakeDtoError(
            f"{prefix}{getattr(model, '__name__', model)!r} is not a compiled model: nothing "
            f"declared it with @snake_model or @snake_db_first, so there is no column list to read."
        )
    for path in exclude or ():
        if len(path) != 1:
            raise SnakeDtoError(
                f"{prefix}{name!r} excludes {'.'.join(path)!r}, which is not one column of the "
                f"model it describes. `exclude=` prunes this model's own columns; the fields of a "
                f"nested DTO come from ITS spec, so there is nothing to prune from here."
            )
    return SnakeDtoSpec(model=model, name=name, fields=fields, exclude=exclude or ())


def _path_of_entry(entry: SnakeDtoEntry, dto: str) -> tuple[str, ...]:
    """The path an entry names, whichever of the three kinds of navigation node it is."""
    if isinstance(entry, SnakePathProxy):
        return path_of(entry)
    if isinstance(entry, SnakeDtoPath):
        return entry.path
    raise SnakeDtoError(
        f"{dto} was given {type(entry).__name__} as a field, which names no column or relationship. "
        f"An entry is class access on a model — `Post.title`, `Post.author.username`, "
        f"`Post.author`, `Post.comments` — and nothing else."
    )


def _pick(item: SnakeDtoSelection, dto: str) -> SnakeDtoPick:
    """One `fields=` entry, with the nested DTO name if it was paired with one."""
    if isinstance(item, tuple):
        entry, named = item
        return SnakeDtoPick(path=_path_of_entry(entry, dto), dto=named)
    return SnakeDtoPick(path=_path_of_entry(item, dto))


def _excluded(item: SnakeDtoSelection, dto: str) -> tuple[str, ...]:
    """One `exclude=` entry, which has to be a plain column of the model being described.

    A path across a relationship reads as if it removed something and removes nothing: the far
    model's columns were never in this DTO to begin with, because a relationship NESTS.
    """
    if isinstance(item, tuple):
        raise SnakeDtoError(
            f"{dto} pairs an exclusion with a DTO name, and there is nothing to name: "
            f"`exclude=` removes columns, it does not nest anything."
        )
    return _path_of_entry(item, dto)
