"""The marked region: the only part of a DTO file this generator owns, and the only part it writes.

A DTO file has two owners with a visible line between them. Above, the specs, which are the user's
and are never edited. Between the markers, the classes, which are the generator's and are rewritten
whole on every run. Nothing outside the two marker lines is ever touched — that is a property of the
splice, not of care taken while writing it.

A marker EARNS its place here in a way it would not have in somebody's own class body. These classes
were never typed by a person: without the boundary there is no way to tell a generated class from a
hand-written one, and a tool that cannot tell would eventually overwrite the wrong thing.

The region is regenerated rather than patched, which is what makes idempotence structural: the same
specs and the same models render the same bytes, so a second run has nothing to write. What is
DIFFED, field by field, is the old region against the new one — and because the region is this
module's own output, it can be read strictly instead of being guessed at.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from snakeorm.core.exceptions import SnakeDtoError
from snakeorm.dto.read import specs_in_source
from snakeorm.dto.resolve import SnakeDtoShape, resolve_all
from snakeorm.helpers.pytype import FROM_SNAKEORM

BEGIN = "# snakeorm-dto: begin generated block"
"""First line of the region. Matched as a PREFIX so the explanation after it can be reworded."""

END = "# snakeorm-dto: end generated block"
"""Last line of the region."""

_HEADER = f"{BEGIN} — written by `snakeorm dto --sync`, edit the specs above"
_FOOTER = END


class SnakeDtoChangeKind(Enum):
    """What happened to one field. Three kinds, because they are three different risks."""

    ADDED = "added"
    REMOVED = "removed"
    RETYPED = "retyped"


@dataclass(frozen=True, slots=True)
class SnakeDtoChange:
    """One field this run added, dropped or retyped, with the text on both sides."""

    dto: str
    field: str
    kind: SnakeDtoChangeKind
    before: str = ""
    after: str = ""

    def describe(self) -> str:
        """The change as ONE line, which is what the command prints.

        Every change is printed, always. A generator that writes into your file and reports only
        failures is a generator you have to `git diff` to trust.
        """
        if self.kind is SnakeDtoChangeKind.ADDED:
            return f"{self.dto}: added `{self.after}`"
        if self.kind is SnakeDtoChangeKind.REMOVED:
            return f"{self.dto}: removed `{self.before}`"
        return f"{self.dto}: retyped `{self.before}` -> `{self.after}`"


@dataclass(frozen=True, slots=True)
class SnakeDtoSyncResult:
    """The source as it should be, and every field that moved to get there."""

    source: str
    changes: tuple[SnakeDtoChange, ...]

    @property
    def changed(self) -> bool:
        """Whether anything moved at all. `False` is what a second run has to say."""
        return bool(self.changes)


def sync_source(source: str, *, path: str = "<source>") -> SnakeDtoSyncResult:
    """The file with its generated region brought in line with its specs, and what that took.

    Nothing is written here — this returns text — so a refusal halfway through cannot leave a file
    half rewritten. And nothing of the user's is ever EXECUTED: the specs are read out of the source
    with `ast`, and the only thing imported is the models module they name.
    """
    specs = specs_in_source(source, path=path)
    lines = source.splitlines(keepends=True)
    start, stop = _locate(lines, path)
    if not specs:
        return SnakeDtoSyncResult(source=source, changes=())
    shapes = resolve_all(specs)
    _check_scope(shapes, source, path)
    newline = _newline_of(lines)
    rendered = _render(shapes, newline)
    existing = lines[start:stop] if start is not None and stop is not None else []
    changes = _diff(_parse_region(existing), shapes)
    if existing == rendered:
        return SnakeDtoSyncResult(source=source, changes=())
    if start is None or stop is None:
        # No region yet: it goes at the END of the file, always, so where it lands is a rule and
        # not a judgement about somebody's layout.
        head = (
            lines
            if not lines or lines[-1].endswith(("\n", "\r"))
            else [*lines[:-1], lines[-1] + newline]
        )
        return SnakeDtoSyncResult(
            source="".join([*head, newline, newline, *rendered]), changes=changes
        )
    return SnakeDtoSyncResult(
        source="".join([*lines[:start], *rendered, *lines[stop:]]), changes=changes
    )


def sync_file(path: Path, *, write: bool) -> SnakeDtoSyncResult:
    """Same over a file on disk. With `write=False` it reports and touches nothing.

    Written only when something actually moved, so a clean run does not restamp the modification
    time and set half the build tooling off.
    """
    result = sync_source(path.read_text(encoding="utf-8"), path=str(path))
    if write and result.changed:
        path.write_text(result.source, encoding="utf-8")
    return result


def _locate(lines: list[str], path: str) -> tuple[int | None, int | None]:
    """Where the region starts and ends, as line indices, or `(None, None)` when there is none.

    Every way of being malformed is an error rather than a repair: an unterminated region has no end
    to write up to, and two regions have no rule saying which is the real one. Guessing either way
    is how a generator eats the half of the file it did not understand.
    """
    starts = [index for index, line in enumerate(lines) if line.startswith(BEGIN)]
    ends = [index for index, line in enumerate(lines) if line.startswith(END)]
    if not starts and not ends:
        return None, None
    if len(starts) > 1 or len(ends) > 1:
        raise SnakeDtoError(
            f"{path} holds more than one generated region, and there is no rule saying which is the "
            f"real one. Nothing was written: delete the extra `{BEGIN}` block."
        )
    if not starts:
        raise SnakeDtoError(
            f"{path} has a `{END}` with no beginning. Nothing was written."
        )
    if not ends:
        raise SnakeDtoError(
            f"{path} opens a generated region at line {starts[0] + 1} and never closes it with "
            f"`{END}`. There is no end to write up to, so nothing was written."
        )
    if ends[0] < starts[0]:
        raise SnakeDtoError(
            f"{path} closes its generated region before it opens it. Nothing was written."
        )
    return starts[0], ends[0] + 1


def _render(shapes: Sequence[SnakeDtoShape], newline: str) -> list[str]:
    """The whole region as lines, markers included. Deterministic, which is where idempotence lives."""
    out = [_HEADER + newline]
    for index, shape in enumerate(shapes):
        if index:
            out.extend([newline, newline])
        out.append(f"class {shape.name}(TypedDict):{newline}")
        for field in shape.fields:
            out.append(f"    {field.name}: {field.annotation}{newline}")
        if not shape.fields:
            # A class body cannot be empty, and a spec CAN legitimately select nothing.
            out.append(f"    pass{newline}")
    out.append(_FOOTER + newline)
    return out


def _parse_region(lines: list[str]) -> dict[str, dict[str, str]]:
    """`{class: {field: annotation}}` for the region as it stands on disk.

    Read with `ast` and not with a regular expression, because this is the generator's own output
    and the shape of it is known exactly. Anything unparseable comes back empty, which reports every
    field as added — loud, and correct: a region that is not what this tool writes IS out of date.
    """
    try:
        tree = ast.parse("".join(line for line in lines if not line.startswith("#")))
    except SyntaxError:
        return {}
    found: dict[str, dict[str, str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        found[node.name] = {
            statement.target.id: ast.unparse(statement.annotation)
            for statement in node.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
        }
    return found


def _diff(
    before: dict[str, dict[str, str]], shapes: Sequence[SnakeDtoShape]
) -> tuple[SnakeDtoChange, ...]:
    """Every field that moved between the region on disk and the one about to be written.

    A whole class appearing reports as its fields being added, and a class disappearing as its
    fields being removed. One vocabulary instead of two: what a reader wants to know is which keys
    the response gained or lost, and a class is only how they are grouped.
    """
    changes: list[SnakeDtoChange] = []
    wanted = {shape.name: shape for shape in shapes}
    for shape in shapes:
        old = before.get(shape.name, {})
        for field in shape.fields:
            written = f"{field.name}: {field.annotation}"
            if field.name not in old:
                changes.append(
                    SnakeDtoChange(
                        dto=shape.name,
                        field=field.name,
                        kind=SnakeDtoChangeKind.ADDED,
                        after=written,
                    )
                )
            elif old[field.name] != field.annotation:
                changes.append(
                    SnakeDtoChange(
                        dto=shape.name,
                        field=field.name,
                        kind=SnakeDtoChangeKind.RETYPED,
                        before=f"{field.name}: {old[field.name]}",
                        after=written,
                    )
                )
        current = {field.name for field in shape.fields}
        for name, annotation in old.items():
            if name not in current:
                changes.append(
                    SnakeDtoChange(
                        dto=shape.name,
                        field=name,
                        kind=SnakeDtoChangeKind.REMOVED,
                        before=f"{name}: {annotation}",
                    )
                )
    for name, old in before.items():
        if name in wanted:
            continue
        for field_name, annotation in old.items():
            changes.append(
                SnakeDtoChange(
                    dto=name,
                    field=field_name,
                    kind=SnakeDtoChangeKind.REMOVED,
                    before=f"{field_name}: {annotation}",
                )
            )
    return tuple(changes)


def _check_scope(shapes: Sequence[SnakeDtoShape], source: str, path: str) -> None:
    """Refuses anything whose name the file does not already have in scope, and writes no imports.

    `TypedDict` is included, and it is the one people forget: the generator writes
    `class X(TypedDict)` and cannot make that resolve on its own. Editing somebody's import block on
    a guess is a much bigger claim on their file than filling a region they marked out; getting it
    wrong means the file stops importing, so the generator would have broken the build to fix a
    type. Saying which line to add costs the reader one line and cannot go wrong.
    """
    in_scope = _names_in_scope(source, path)
    if "TypedDict" not in in_scope:
        raise SnakeDtoError(
            f"{path} does not have `TypedDict` in scope, and every generated class is written "
            f"`class X(TypedDict)`. Add `from typing import TypedDict` yourself: this command "
            f"writes classes, never imports."
        )
    for shape in shapes:
        for field in shape.fields:
            if field.requires is None:
                continue
            if field.requires == FROM_SNAKEORM:
                symbol = field.annotation.split(" ")[0]
                needed, line = symbol, f"from snakeorm import {symbol}"
            else:
                needed = field.requires.split(".")[0]
                line = f"import {field.requires}"
            if needed not in in_scope:
                raise SnakeDtoError(
                    f"{shape.name} needs `{field.name}: {field.annotation}` and {path} does not "
                    f"have `{needed}` in scope. Add `{line}` yourself and run this again: this "
                    f"command writes classes, never imports."
                )


def _names_in_scope(source: str, path: str) -> set[str]:
    """Every name the file's imports bind, wherever in the file they are written.

    The whole tree, so an import parked under `if TYPE_CHECKING:` counts — which is exactly where a
    name used only in annotations belongs, and where these specs live. Being generous here can only
    let a class THROUGH; the checker reads the same file and has the last word.
    """
    bound: set[str] = set()
    for node in ast.walk(ast.parse(source, filename=path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
    return bound


def _newline_of(lines: list[str]) -> str:
    """The file's line ending, so what gets inserted matches what is already there."""
    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return "\n"
