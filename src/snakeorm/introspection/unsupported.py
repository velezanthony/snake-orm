"""The ONE catalogue of `unsupported` warnings, shared by the three introspectors.

Every engine asks its own catalogue — `pg_catalog`, `information_schema`, `sqlite_master` — and that
difference is permanent and legitimate. What none of them does any more is WORD the answer: each
query tags every row with a kind and hands over the pieces, and the sentence is written here.

It used to be written inside each engine's SQL, and the three drifted exactly as one would expect
from three copies nothing compares. For the same finding Postgres emitted `columna de tipo no
representable: ` and MySQL `column of a type with no equivalent: `; where those two said
`trigger: {name} on {table}`, SQLite said `trigger not representable in the model: {name}` and never
named the table. One of the three was in Spanish, and it did not merely get printed: `cli/app.py`
writes these sentences as comments inside the `models.py` that `scaffold` generates and the user
commits into their own repository.

The sentence IS the product here. It is the only trace left of what the mirror does not cover, and
whoever reads the generated file has nothing else to tell them the database holds more than this.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum


class SnakeUnsupportedKind(StrEnum):
    """What an `unsupported` row describes. It travels as the row's FIRST column.

    The engines agree on this vocabulary and disagree on which of these kinds they can detect, which
    is a difference in what each catalogue is able to answer — not a difference in wording.
    """

    TRIGGER = "trigger"
    ROUTINE = "routine"
    EXPRESSION_INDEX = "expression_index"
    UNREPRESENTABLE_COLUMN = "unrepresentable_column"
    CHECK = "check"


def trigger_warning(name: str, table: str) -> str:
    """A trigger: still there and still firing, and the model has no way to mention it."""
    return f"trigger: {name} on {table}"


def check_warning(name: str, table: str, expression: str) -> str:
    """A CHECK constraint: the database rejects rows the model believes are fine.

    `snake_check` takes a `SnakeCondition`, never a string, so a mirror cannot declare one:
    rebuilding the condition from the server's own text would be writing a SQL parser per engine.
    The expression travels VERBATIM because it is the only thing that tells the reader what is
    being enforced behind their model.
    """
    return f"check: {name} on {table} ({expression})"


def routine_warning(name: str) -> str:
    """A stored routine (procedure or function): the metadata graph has no place for one."""
    return f"routine: {name}"


def expression_index_warning(name: str) -> str:
    """An index over an EXPRESSION: the graph indexes columns, never expressions."""
    return f"expression index: {name}"


def unrepresentable_column_warning(table: str, column: str, sql_type: str) -> str:
    """A column whose SQL type has no equivalent in a Python annotation."""
    return f"column of a type with no equivalent: {table}.{column} ({sql_type})"


def warning_from_row(row: Sequence[object]) -> str:
    """Word one `(kind, first, second, third)` row of an engine's unsupported query.

    An unknown kind blows up instead of being skipped. Skipping would be the exact silence this
    module exists to prevent: the engine bothered to report the object, and dropping it quietly is
    what makes a mirror look complete when it is not.
    """
    kind = SnakeUnsupportedKind(str(row[0]))
    first, second, third = ("" if piece is None else str(piece) for piece in row[1:4])
    match kind:
        case SnakeUnsupportedKind.TRIGGER:
            return trigger_warning(first, second)
        case SnakeUnsupportedKind.ROUTINE:
            return routine_warning(first)
        case SnakeUnsupportedKind.EXPRESSION_INDEX:
            return expression_index_warning(first)
        case SnakeUnsupportedKind.UNREPRESENTABLE_COLUMN:
            return unrepresentable_column_warning(first, second, third)
        case SnakeUnsupportedKind.CHECK:
            return check_warning(first, second, third)


def warnings_from_rows(rows: Sequence[Sequence[object]]) -> list[str]:
    """Word every row an engine's unsupported query returned, in the order it returned them."""
    return [warning_from_row(row) for row in rows]
