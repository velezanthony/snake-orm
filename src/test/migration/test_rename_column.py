"""`RenameColumn`: renaming without losing the data, and a warning when the diff smells of a rename.

The diff compares columns by NAME, so renaming one produces `DropColumn` + `AddColumn`:
syntactically correct and catastrophic, because it wipes the data of the old column.

The operation is EXPLICIT on purpose. A heuristic that decides on its own —"a drop and an add of the
same type, must be a rename"— gets it right almost every time and the day it fails it renames a
column you wanted dropped, with another's data inside. Here the diff SUGGESTS, the human decides.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import (
    RenameColumn,
    SchemaState,
    diff_schema,
    rename_suggestions,
)

_DIALECT = PostgresDialect()
_ID = SnakeColumnInfo(name="id", python_type=int)


def _table(*columns: SnakeColumnInfo) -> SnakeTableInfo:
    """The 'users' table with the given columns plus the PK."""
    return SnakeTableInfo(
        name="users",
        columns=(_ID, *columns),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    )


def test_up_renames_and_down_puts_it_back() -> None:
    """Verifies that the rename is genuinely reversible (and that it does NOT touch the data)."""
    operation = RenameColumn(_table(), old_name="mail", new_name="email")

    assert operation.up_sql(_DIALECT) == [
        'ALTER TABLE "public"."users" RENAME COLUMN "mail" TO "email"'
    ]
    assert operation.down_sql(_DIALECT) == [
        'ALTER TABLE "public"."users" RENAME COLUMN "email" TO "mail"'
    ]


def test_apply_to_state_renames_the_column_in_place() -> None:
    """Verifies that the abstract state reflects the rename, keeping the rest of the column."""
    old = SnakeColumnInfo(name="mail", python_type=str, db_comment="correo")
    state = SchemaState([_table(old)])

    RenameColumn(_table(old), old_name="mail", new_name="email").apply_to_state(state)

    table = state.get_table("users")
    assert table is not None
    renamed = table.get_column("email")
    assert renamed is not None
    assert renamed.db_comment == "correo", (
        "the rename must not lose the rest of the definition"
    )
    assert table.get_column("mail") is None


def test_the_diff_still_refuses_to_guess() -> None:
    """Verifies that the diff does NOT decide on its own: it keeps emitting drop + add.

    That is deliberate. Guessing a rename wrong means moving data into the wrong column.
    """
    before = _table(SnakeColumnInfo(name="mail", python_type=str))
    after = _table(SnakeColumnInfo(name="email", python_type=str))

    kinds = [type(op).__name__ for op in diff_schema([before], [after])]
    assert kinds == ["AddColumn", "DropColumn"]


def test_it_suggests_the_rename_it_can_see() -> None:
    """Verifies the WARNING: a drop and an add of the same type in the same table get flagged."""
    before = _table(SnakeColumnInfo(name="mail", python_type=str))
    after = _table(SnakeColumnInfo(name="email", python_type=str))

    suggestions = rename_suggestions(diff_schema([before], [after]))

    assert suggestions == [("users", "mail", "email")]


def test_it_does_not_suggest_across_different_types() -> None:
    """Verifies that it suggests no rename across different types: there it surely is not one."""
    before = _table(SnakeColumnInfo(name="mail", python_type=str))
    after = _table(SnakeColumnInfo(name="age", python_type=int))

    assert rename_suggestions(diff_schema([before], [after])) == []


def test_it_does_not_suggest_when_the_pairing_is_ambiguous() -> None:
    """Verifies that with SEVERAL candidates of the same type it keeps quiet.

    With two columns dropped and two added, all of them text, any pairing is a bet. Suggesting
    the wrong pair is worse than suggesting nothing at all.
    """
    before = _table(
        SnakeColumnInfo(name="mail", python_type=str),
        SnakeColumnInfo(name="phone", python_type=str),
    )
    after = _table(
        SnakeColumnInfo(name="email", python_type=str),
        SnakeColumnInfo(name="mobile", python_type=str),
    )

    assert rename_suggestions(diff_schema([before], [after])) == []


def test_no_suggestion_when_nothing_looks_like_a_rename() -> None:
    """Verifies that plainly adding a column fires no warning at all."""
    before = _table()
    after = _table(SnakeColumnInfo(name="email", python_type=str))

    assert rename_suggestions(diff_schema([before], [after])) == []


def test_the_narrowing_hint_speaks_ONE_language() -> None:
    """The CLI prefix of a narrowing warning is English, like the sentence it prefixes.

    This file carried two prefixes for the same job: the rename suggestion said `Warning:` and the
    narrowing hint said `Aviso:` — glued onto a sentence that was in English anyway, so a user got
    two languages in one line. Nothing asserted either of them, which is how they drifted apart
    inside a single module.

    The check is an EQUALITY on what the function returns, not a judgement about words: the two
    prefixes have to be the same string, whatever that string is.
    """
    from snakeorm.migration.renames import format_narrowing_hint

    hint = format_narrowing_hint(
        ["users.price narrows NUMERIC(12,2) -> NUMERIC(10,2)."]
    )

    assert hint == "Warning: users.price narrows NUMERIC(12,2) -> NUMERIC(10,2)."


def test_no_narrowings_means_no_message_at_all() -> None:
    """With nothing to warn about the hint is empty, so the CLI prints no orphan heading."""
    from snakeorm.migration.renames import format_narrowing_hint

    assert format_narrowing_hint([]) == ""


def test_both_prefixes_of_this_module_are_the_same_word() -> None:
    """The rename suggestion and the narrowing hint prefix their line with the SAME word.

    They are two doors of one module and a user meets them in the same terminal. Asserting one
    against the other is what keeps them together: it fails whichever of the two someone changes.
    """
    from snakeorm.migration.renames import format_narrowing_hint, format_rename_hint

    rename = format_rename_hint(
        rename_suggestions(
            diff_schema(
                [_table(SnakeColumnInfo(name="mail", python_type=str))],
                [_table(SnakeColumnInfo(name="email", python_type=str))],
            )
        )
    )
    narrowing = format_narrowing_hint(["x"])

    assert rename, "the rename hint is the other half of this comparison"

    def prefix_of(message: str) -> str:
        """The word before the first colon of the first line."""
        return message.splitlines()[0].split(":", 1)[0]

    assert prefix_of(narrowing) == prefix_of(rename) == "Warning"
