"""What the generator FLAGS for the person in front of it. It suggests; it does not decide.

The file is named after the first of them and now holds three, which is worth saying rather than
leaving for the next reader to discover: possible column renames, narrowing type changes, and a
destructive operation under standing views. They belong together because they share one rule —
each one is emitted at GENERATION time, when there is somebody there to read it, and none of them
edits the plan. A heuristic that decides on its own will, the day it gets it wrong, move data into
the wrong column in silence.

A rename reaches the diff as `DropColumn` + `AddColumn` (correct but catastrophic: it deletes the
data). The diff is not corrected here, it is only flagged so a human can write a `RenameColumn`.
That is also why it stays quiet in the face of AMBIGUITY (several candidates of the same type).
"""

from __future__ import annotations

from collections.abc import Sequence

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import SnakeTableInfo
from snakeorm.migration.ddl import sql_type_of
from snakeorm.migration.operations import (
    AddColumn,
    AlterColumn,
    DropColumn,
    DropTable,
    RebuildTable,
    SnakeMigrationOperation,
)

# (table, old name, new name)
RenameSuggestion = tuple[str, str, str]


def rename_suggestions(
    operations: Sequence[SnakeMigrationOperation],
) -> list[RenameSuggestion]:
    """(drop, add) pairs of the SAME type and table that are probably a rename.

    A suggestion only comes out when the pairing is UNAMBIGUOUS: exactly one dropped column and one
    added column of that type in that table. With more candidates, silence.
    """
    dropped: dict[tuple[str, type], list[str]] = {}
    added: dict[tuple[str, type], list[str]] = {}

    for operation in operations:
        if isinstance(operation, DropColumn):
            key = (operation.table.name, operation.column.python_type)
            dropped.setdefault(key, []).append(operation.column.name)
        elif isinstance(operation, AddColumn):
            key = (operation.table.name, operation.column.python_type)
            added.setdefault(key, []).append(operation.column.name)

    suggestions: list[RenameSuggestion] = []
    for key, old_names in sorted(dropped.items(), key=lambda item: item[0][0]):
        new_names = added.get(key, [])
        if len(old_names) != 1 or len(new_names) != 1:
            continue  # ambiguous (or no counterpart): nothing is guessed
        suggestions.append((key[0], old_names[0], new_names[0]))
    return suggestions


def format_rename_hint(suggestions: Sequence[RenameSuggestion]) -> str:
    """Message for the CLI with the suspected renames, or an empty string if there are none."""
    if not suggestions:
        return ""
    lines = [
        "Warning: this could be a RENAME, and as it stands it DELETES the old column's data.",
    ]
    lines.extend(
        f"  - {table}: did you rename '{old}' to '{new}'? Replace its DropColumn + AddColumn "
        f'with RenameColumn({table}, old_name="{old}", new_name="{new}").'
        for table, old, new in suggestions
    )
    return "\n".join(lines)


def narrowing_warnings(operations: Sequence[SnakeMigrationOperation]) -> list[str]:
    """Type changes that NARROW the column and may not fit the existing rows.

    Narrowing a `NUMERIC(12,2)` to `NUMERIC(10,2)` makes `migrate` fail if some row does not fit;
    warning at GENERATION time beats finding out during the deploy. It only points, it does not
    block: narrowing is usually intentional and safe.
    """
    dialect = PostgresDialect()
    warnings_: list[str] = []
    for operation in operations:
        if not isinstance(operation, AlterColumn):
            continue
        if (operation.old.precision or 0) <= (operation.new.precision or 0):
            continue  # not a narrowing: same width or wider
        warnings_.append(
            f"{operation.table.name}.{operation.new.name} narrows "
            f"{sql_type_of(operation.old, dialect)} -> {sql_type_of(operation.new, dialect)}. "
            f"Rows that do not fit will make the migrate fail. Check the data before applying it."
        )
    return warnings_


def format_narrowing_hint(warnings_: Sequence[str]) -> str:
    """Message for the CLI with the detected narrowings, or an empty string if there are none."""
    if not warnings_:
        return ""
    return "\n".join(f"Warning: {warning}" for warning in warnings_)


def standing_view_warning(
    operations: Sequence[SnakeMigrationOperation],
    state_tables: Sequence[SnakeTableInfo],
) -> str:
    """A plan that DESTROYS a table while views stand, stated as two facts and a question.

    THE CONDITION IS DOUBLE, and that is what keeps it from becoming background noise. It takes a
    destructive operation over a table — `RebuildTable` or `DropTable` — AND at least one view in
    the replayed state. A migration that only adds a column says nothing even in a schema full of
    views, and a migration that drops ten tables says nothing in a schema with no view.

    THE TWO DESTRUCTIONS FAIL DIFFERENTLY, which is why both are in. A `RebuildTable` ends, on the
    engine that cannot alter a constraint in place, in a `RENAME` that REPARSES the whole schema: a
    view that reads the table makes it fail and the migration rolls back — loud, and at deploy time.
    A `DropTable` is worse: SQLite resolves a view lazily, so the drop goes through and leaves the
    view DANGLING. Nothing reports that until somebody queries it or the next rename reparses.

    WHAT IT MAY NOT SAY IS WHICH VIEW READS WHICH TABLE, because it does not know. `depends_on` is
    view->view only, `SnakeTableInfo` has no field naming the tables a view reads, and a view
    declared with `sql=` is raw text. So the message states the two sets, says out loud that the
    pairing is the reader's to make, and names what to write if it is real.

    Returns an empty string when there is nothing to say.
    """
    rebuilt = sorted(
        {op.after.name for op in operations if isinstance(op, RebuildTable)}
    )
    dropped = sorted({op.table.name for op in operations if isinstance(op, DropTable)})
    views = sorted({table.name for table in state_tables if table.is_view})
    if not views or not (rebuilt or dropped):
        return ""
    destroyed: list[str] = []
    if rebuilt:
        destroyed.append(f"rebuilds {', '.join(rebuilt)}")
    if dropped:
        destroyed.append(f"drops {', '.join(dropped)}")
    return (
        f"This migration {' and '.join(destroyed)}, and the schema has these views standing: "
        f"{', '.join(views)}. SnakeORM cannot tell you which of those views read those tables: "
        f"nothing in the metadata says it — `depends_on` names other views only, and a view "
        f"declared with `sql=` is raw text — so that pairing is yours to make. Read the view "
        f"definitions. If one of them does read one of those tables, put a DropView of it BEFORE "
        f"the operation and a CreateView of it AFTER, in this same file: a rebuild ends in a "
        f"RENAME that reparses the whole schema and the migration will fail halfway, and a dropped "
        f"table leaves the view standing but broken, which nothing reports until somebody queries "
        f"it."
    )
