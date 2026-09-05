"""Every migration operation says whether it needs a capability, or says it needs none.

`realize` refuses an operation the engine cannot perform, and it does it from a TABLE
(`_REQUIREMENTS`) that pairs an operation with the `Cap` it depends on. The table is written by hand,
which is fine — what was missing is anything checking that a new operation reaches it.

WHAT THAT COST, MEASURED. `CreateFunction` and `DropFunction` are in the table; `AlterFunction` was
not. So a migration that ALTERS a stored function was planned without complaint on SQLite and MySQL —
neither of which has stored functions at all — and the driver was left to explain. Same for
`AlterTableComment` on the two engines that store no comments.

It is the third time this exact shape appears in this repository: `count()` fixed and its two
brothers left (#18), `exists()` left out of the knob guard (#21), and now the third member of the
function family. Recognising a pattern does not vaccinate against it; only a check does.

SO THE CHECK IS EXHAUSTIVE BY CONSTRUCTION. It reads the operation classes out of the module and
demands that each one appear in exactly one of two places: the requirements table, or the list below
of operations that work on every engine — WITH the reason they do. An operation that is in neither
fails this test on the day it is written, which is the day the decision is cheap.

WHY NOT DERIVE IT FROM THE SIBLINGS. That was tried and it is wrong: grouping by the noun
(`AddColumn`, `DropColumn`, `RenameColumn`, `AlterColumn`) says the first three should be guarded
because the fourth is, and they should not — SQLite adds, drops and renames columns perfectly well
and only refuses to ALTER one. A rule that produces a false positive on its first family is a rule
that gets an exemption list, and an exemption list is where things go to hide.
"""

from __future__ import annotations

import inspect

from snakeorm.migration import operations
from snakeorm.migration.realize import _REQUIREMENTS

# Operations that need NO capability, each with the reason it needs none. The reason is not decoration
# — it is what makes adding a line here a decision instead of a way to silence the test.
_WORKS_EVERYWHERE: dict[str, str] = {
    "CreateTable": (
        "every engine creates tables; the FKs go inside when it cannot ADD CONSTRAINT. It carries "
        "the table's indexes, so `_guard_partial_index` reads it too — a CONDITIONAL requirement "
        "that depends on the index and not on the operation, which is why it is not in the table "
        "below and has its own check in `test_partial_indexes_per_engine`"
    ),
    "DropTable": (
        "every engine drops tables; what two of the three refuse is dropping one a foreign key "
        "still points at, and that is a question of ORDER and not of capability — `drop_order` "
        "retires the holder first, so nothing has to be refused"
    ),
    "AddColumn": "ALTER TABLE ADD COLUMN is universal, SQLite included",
    "DropColumn": (
        "ALTER TABLE DROP COLUMN is universal since SQLite 3.35 — but NOT over a column a foreign "
        "key still holds, which MySQL refuses with error 1553 and SQLite with 'unknown column in "
        "foreign key definition'. That depends on the COLUMN and on what the plan already did, not "
        "on the operation's type, so `_REQUIREMENTS` could not express it without refusing every "
        "column drop on two engines: it is guarded by `_guard_dropped_fk_column` and checked by "
        "`test_drop_column_with_foreign_key`"
    ),
    "RenameColumn": "ALTER TABLE RENAME COLUMN is universal; it is ALTERING one that SQLite refuses",
    "RenameTable": (
        "ALTER TABLE ... RENAME TO is universal, and MEASURED on the three servers rather than "
        "assumed: PostgreSQL 17, MariaDB 11.8.8 and SQLite 3.50.4 all take it, and all three keep "
        "the foreign keys that point AT the renamed table standing. What differs is only the "
        "quoting and whether the OLD name carries a schema, which `qualified` already writes — the "
        "NEW name is bare on all three, because Postgres rejects a qualified one outright"
    ),
    "RebuildTable": (
        "it is the way OUT of a refusal, not one: it exists precisely so the engine WITHOUT "
        "`ALTER TABLE ... ADD CONSTRAINT` has a way to change a CHECK or a foreign key on a table "
        "that already exists. Gating it on `Cap.ADD_CONSTRAINT` — the capability its own siblings "
        "`AddCheck` and `DropCheck` are gated on — would refuse it on the one engine it was written "
        "for. Where the capability IS there, the dialect emits the minimal `ALTER` instead of "
        "remaking anything"
    ),
    "CreateIndex": (
        "every engine indexes; a UNIQUE falls back to a unique index where it must. What it needs "
        "depends on the INDEX and not on the operation —only a partial UNIQUE one is refused, and "
        "only where `Cap.PARTIAL_INDEXES` is missing— so it is guarded by `_guard_partial_index` "
        "rather than by the type table, which can only express 'always'"
    ),
    "DropIndex": "every engine drops indexes; only the SYNTAX differs, and the dialect writes it",
    "AddForeignKey": (
        "`realize` handles it before this table does: where there is no ADD CONSTRAINT it is folded "
        "into the CreateTable, and refused with its own message when the table already exists"
    ),
    "DropForeignKey": "same path as AddForeignKey, with its own message in `realize`",
    "CreateView": "every engine creates views",
    "DropView": "every engine drops views",
    "AlterView": (
        "translated, not refused: without CREATE OR REPLACE VIEW the dialect rewrites it as "
        "DropView + CreateView. Measured on SQLite"
    ),
    "CreateTrigger": (
        "every engine has triggers; the BODY is spelt differently and the dialect translates it "
        "(PostgreSQL wraps it in a function and calls it)"
    ),
    "DropTrigger": "same as CreateTrigger; on PostgreSQL it drops the generated function too",
    "AlterTrigger": "a DropTrigger plus a CreateTrigger, so it inherits both",
    "RunSQL": "raw SQL the user wrote: whether the engine takes it is the user's business",
    "RunPython": "it runs Python against a session and emits no DDL at all",
}

# The two names the module exports that are PROTOCOLS rather than operations somebody can write.
_NOT_AN_OPERATION = frozenset({"SnakeOperation", "SnakeDataOperation"})


def _operation_names() -> set[str]:
    """The operation classes, read FROM THE MODULE so a new one cannot be missed."""
    return {
        name
        for name, value in inspect.getmembers(operations, inspect.isclass)
        if not name.startswith("_")
        and name not in _NOT_AN_OPERATION
        and value.__module__ == operations.__name__
        and (hasattr(value, "up_sql") or hasattr(value, "run"))
    }


def test_the_operations_are_discovered() -> None:
    """The introspection found them. Without this, every check below holds over an empty set."""
    assert len(_operation_names()) >= 20, sorted(_operation_names())


def test_every_operation_is_either_gated_or_declared_universal() -> None:
    """The whole point: an operation in NEITHER list is one nobody decided about.

    This is what `AlterFunction` fell through. It planned cleanly on two engines that have no stored
    functions, and the failure arrived from the driver, at apply time, on somebody's deploy.
    """
    gated = {operation.__name__ for operation, _, _ in _REQUIREMENTS}
    undecided = sorted(_operation_names() - gated - set(_WORKS_EVERYWHERE))

    assert undecided == [], (
        f"these operations say nothing about what they need: {undecided}. Put each one in "
        f"`_REQUIREMENTS` with the `Cap` it depends on, or in `_WORKS_EVERYWHERE` with the reason it "
        f"depends on none. Planning an operation the engine cannot perform means the DRIVER is what "
        f"explains it, at apply time."
    )


def test_no_operation_claims_both() -> None:
    """An operation cannot both need a capability and need none."""
    gated = {operation.__name__ for operation, _, _ in _REQUIREMENTS}
    both = sorted(gated & set(_WORKS_EVERYWHERE))

    assert both == [], f"listed as gated AND as universal: {both}"


def test_the_universal_list_names_operations_that_exist() -> None:
    """A rename must not leave a ghost behind: an entry for something uncallable can never close."""
    ghosts = sorted(set(_WORKS_EVERYWHERE) - _operation_names())

    assert ghosts == [], f"listed as universal and not an operation any more: {ghosts}"


def test_every_universal_entry_gives_a_reason() -> None:
    """A blank reason is a way to silence this test, which is the one thing it must not offer."""
    empty = sorted(
        name for name, reason in _WORKS_EVERYWHERE.items() if not reason.strip()
    )

    assert empty == [], f"listed as universal with no reason: {empty}"
