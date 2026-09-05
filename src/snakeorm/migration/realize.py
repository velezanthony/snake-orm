"""Landing an (engine-agnostic) migration plan on a concrete engine.

The mismatch between what the plan asks for and the SHAPE each engine accepts is resolved HERE, in
one single place (not with an `if dialect...` inside every `up_sql`). The oldest translation is
SQLite's FKs (`supports_add_constraint=False`): if the table is born in this plan, its FK already
travelled inside the `CREATE TABLE` and the `AddForeignKey` is redundant; if it already existed,
SQLite cannot add it and that is SAID out loud (a green plan that leaves the database without the
declared integrity is worse than one that refuses).

There are two kinds of gate, and mixing them is what this file keeps apart:

- `_guard_capability` reads a TABLE of operation -> capability. It can only say "always": the
  operation needs the capability whatever it carries.
- `_guard_partial_index` is CONDITIONAL — the same `CreateIndex` is fine or refused depending on the
  index inside it, so it cannot be a row in that table without refusing every index on MySQL. The
  sentence above applies twice over: a partial UNIQUE silently widened into a full one is a green
  plan that leaves the database enforcing a rule the model never declared.
- `_guard_dropped_fk_column` is conditional on the PLAN, which is one step further out: the same
  `DropColumn` is fine or refused depending on whether an earlier operation already took the
  foreign key out of the way. Nothing about the operation on its own can answer that.
"""

from __future__ import annotations

from collections.abc import Sequence

from snakeorm.dialects import SnakeDialect
from snakeorm.dialects.capabilities import Cap, Nope
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.migration.ddl import foreign_key_name, inlined_foreign_keys
from snakeorm.metadata import (
    SnakeIndexInfo,
    SnakeRelationshipInfo,
    SnakeRelationshipKind,
    SnakeTableInfo,
)
from snakeorm.migration.operations import (
    AddCheck,
    AddForeignKey,
    AlterColumn,
    AlterFunction,
    AlterTableComment,
    AlterView,
    CreateFunction,
    CreateIndex,
    CreateSchema,
    CreateTable,
    CreateView,
    DropCheck,
    DropColumn,
    DropForeignKey,
    DropFunction,
    DropSchema,
    DropTable,
    DropView,
    RebuildTable,
    SnakeMigrationOperation,
)


def realize(
    operations: Sequence[SnakeMigrationOperation], dialect: SnakeDialect
) -> list[SnakeMigrationOperation]:
    """Returns the plan exactly as it must be applied on this engine.

    With `supports_add_constraint` it returns the SAME plan untouched. It serves both directions: the
    `CreateTable`/`DropTable` pair covers them (if the table is born or dies here, its FK goes with
    it).
    """
    created = {
        operation.table.name
        for operation in operations
        if isinstance(operation, CreateTable | DropTable)
    }
    plan: list[SnakeMigrationOperation] = []
    # Grows AS THE PLAN IS WALKED, and that is the point: a `DropForeignKey` only clears the way for
    # a `DropColumn` that comes AFTER it. A set built up front would accept the two in the wrong
    # order, which is precisely the order the server refuses.
    keys_already_dropped: set[tuple[str, str]] = set()
    for operation in operations:
        _guard_capability(operation, dialect)
        _guard_partial_index(operation, dialect)
        _guard_dropped_fk_column(operation, dialect, keys_already_dropped)
        if isinstance(operation, DropForeignKey):
            keys_already_dropped.update(
                _held_columns(operation.table, operation.relationship)
            )
        if isinstance(operation, RebuildTable):
            # A rebuild that leaves a key behind has REMOVED it, as surely as a `DropForeignKey`
            # would have. Not counting it here would refuse a plan that is correct — the guard's
            # whole job is telling "the key is still standing" from "somebody already took it out",
            # and a rebuild is the other way of taking it out on the engine that has no other.
            keys_already_dropped.update(_keys_removed_by(operation))
        if not dialect.supports_replace_view and isinstance(operation, AlterView):
            # Without `CREATE OR REPLACE VIEW`, altering a view means dropping and creating it. The
            # plan is rewritten here (not in the emitter, which knows nothing about engines).
            plan.extend((DropView(operation.old), CreateView(operation.new)))
            continue
        if dialect.supports_add_constraint or not isinstance(
            operation, AddForeignKey | DropForeignKey
        ):
            plan.append(operation)
            continue
        if operation.table.name not in created:
            carries = (
                "carries" if isinstance(operation, AddForeignKey) else "leaves out"
            )
            raise SnakeMigrationError(
                f"The foreign key '{operation.relationship.name}' of table "
                f"'{operation.table.name}' cannot be applied: this engine does not know how to "
                f"add constraints to an existing table (`ALTER TABLE ... ADD CONSTRAINT`), so the "
                f"table has to be remade around the key. The ORM owns that operation: a "
                f"`RebuildTable` creates the new table with the right constraints inside, copies "
                f"the rows, drops the old one and renames — and the autodetected migration writes "
                f"one by itself when the constraints are the table's ONLY change. Reaching this "
                f"`{type(operation).__name__}` means the plan was written by hand, or the same "
                f"migration also moves a column, an index or the table comment: split those into "
                f"their own migration, or replace this operation with a `RebuildTable` whose "
                f"`after` {carries} '{operation.relationship.name}'."
            )
        if operation.relationship not in inlined_foreign_keys(operation.table, dialect):
            raise SnakeMigrationError(
                f"The foreign key '{operation.relationship.name}' of table "
                f"'{operation.table.name}' has no resolved target (`target_table` is empty), so it "
                f"could not be written inside the `CREATE TABLE` and this engine does not accept "
                f"adding it afterwards. Check that `snake_link()` ran before the migration was "
                f"generated."
            )
    return plan


# Operation -> (the capability enabling it, the reason if the engine lacks it). It is a TABLE and not
# a chain of `if`s so it can be read at a glance and checked that every plan capability appears here
# (otherwise it stays declared but unread, as `supports_add_constraint` was for months).
#
# The capability goes in as a member of `Cap` and NOT as the flag's name in a string, which is how it
# used to be. With the string, `getattr(dialect, flag)` resolved at run time: renaming or moving a
# flag broke nothing at compile time, and this table went on asking about something that no longer
# existed. `AlterColumn` came to be the only place `supports_alter_column` was read, and it was here,
# inside a string.
_REQUIREMENTS: tuple[tuple[type, Cap, str], ...] = (
    (
        CreateSchema,
        Cap.SCHEMAS,
        # It names TWO edits, and the second is the one that unblocks anything. The advice used to
        # stop at "drop the `schema=` from the models", which does not move what is being refused:
        # the `CreateSchema` in front of the runner comes out of a migration FILE, already written
        # and sitting on disk. Editing the models only changes what the NEXT autodetect emits, so
        # the reader follows the instruction, runs the migration again and meets the same sentence.
        "this engine has no named schemas (SQLite's are ATTACHED databases, a different thing). "
        "Drop the `schema=` from the models this connection serves AND regenerate the migration "
        "that carries this `CreateSchema`: editing the models only changes what the next "
        "autodetect writes, and the file the runner is holding is still on disk.",
    ),
    (
        DropSchema,
        Cap.SCHEMAS,
        # The same two edits as its twin above, and it used to give neither. "There is none to drop"
        # is a true fact about the engine and no answer at all to the person holding the file: their
        # migration still carries the operation, and reading that the schema was never there does
        # not tell them what to do about the line in front of them.
        "this engine has no named schemas, so there is none to drop. Drop the `schema=` from the "
        "models this connection serves AND regenerate the migration that carries this "
        "`DropSchema`: editing the models only changes what the next autodetect writes, and the "
        "file the runner is holding is still on disk.",
    ),
    (
        AlterColumn,
        Cap.ALTER_COLUMN,
        # The one entry that really does end at `RunSQL`, and it says so on purpose now that its
        # neighbours point at `RebuildTable`: that operation refuses a pair of snapshots disagreeing
        # about a column (its `__post_init__` names the fields), because SQLite would apply the
        # difference and Postgres would not. So there is no ORM-owned door here, and sending the
        # reader to try one would cost them a run to find out.
        "this engine does not know how to alter an existing column. On SQLite the table has to be "
        "rebuilt (create the new one, copy the rows, drop the old one and rename), and this is the "
        "one case the ORM does NOT do for you: `RebuildTable` only carries constraints and refuses "
        "a pair that disagrees about a column, so do it with an explicit `RunSQL`.",
    ),
    (
        AddCheck,
        Cap.CHECK_CONSTRAINT_DDL,
        # It EXPLAINS, like its `DropCheck` twin below, and it points at the door the ORM OWNS:
        # `RebuildTable` is an operation this module imports, and `diff_schema` collapses a pure
        # constraint change into one. A refusal that names a closed door costs the reader a run.
        "this engine does not know how to add a constraint to an existing table: a CHECK can only "
        "travel inside the `CREATE TABLE`, so putting one on a table that is already there takes "
        "rebuilding the whole table (create the new one with the CHECK inside, copy the rows, drop "
        "the old one and rename). The ORM owns that: it is `RebuildTable`, and the autodetected "
        "migration writes one whenever the constraints are the table's ONLY change. Reaching this "
        "`AddCheck` means it was written by hand, or the same migration also moves a column, "
        "an index or the table comment: split those into their own migration, or replace this "
        "operation with the `RebuildTable`.",
    ),
    (
        DropCheck,
        Cap.CHECK_CONSTRAINT_DDL,
        "this engine does not know how to drop a constraint from an existing table: it would take "
        "rebuilding the whole table, which is what `RebuildTable` does and what the autodetected "
        "migration emits when the constraints are the table's ONLY change.",
    ),
    # Both used to ask about `supports_schemas`, which is not the same thing: an engine can store
    # functions and have no schemas. It coincided across all three engines, so it worked and nobody
    # saw it; the catalogue exposed it by demanding STORED_FUNCTIONS have a reader of its own.
    (
        CreateFunction,
        Cap.STORED_FUNCTIONS,
        "this engine has no stored functions for a migration to create. The body of a "
        "`snake_function` is written in its engine's dialect, so it was never portable.",
    ),
    (
        DropFunction,
        Cap.STORED_FUNCTIONS,
        "this engine has no stored functions for a migration to drop.",
    ),
    # The THIRD member of the family, and it was missing while its two brothers were here. A plan
    # that alters a function was accepted on engines with no stored functions at all, and the driver
    # was what explained it — at apply time, on somebody's deploy.
    (
        AlterFunction,
        Cap.STORED_FUNCTIONS,
        "this engine has no stored functions for a migration to alter.",
    ),
    # The reason used to name MySQL as one of the engines that cannot, and it was FALSE: measured,
    # MariaDB stores the comment and `ALTER TABLE t COMMENT = 'x'` replaces it. The dialect had
    # confused "it spells it differently" with "it cannot", so this refusal was firing on an engine
    # that does the job — with a sentence, "there is no comment to change", that was not true of it.
    # Only the engine the sentence was always true about is left.
    (
        AlterTableComment,
        Cap.COMMENTS,
        "this engine stores no comment at all, so there is no comment to change. It is not a "
        "question of spelling: MySQL writes it as a clause instead of a statement and the dialect "
        "translates that, but SQLite has nowhere to put one.",
    ),
)


_INDEX_CREATORS: tuple[type, ...] = (CreateIndex, CreateTable)
"""The operations that put an index INTO the database. Two, and the second is the easy one to miss.

`CreateIndex` carries one explicitly; `CreateTable` emits the whole table's indexes inline, and that
is the path a first migration takes — and the one the demos' bootstrap takes. A guard that only knew
about `CreateIndex` would report itself green over the case that actually breaks.

It is a tuple and not an `isinstance` chain buried inside the function so that
`test_the_guard_sees_every_operation_that_creates_an_index` can compare it against the operations
that really emit a `CREATE INDEX`, read out of their own source. This guard is CONDITIONAL —it
depends on the index carried, not on the operation's type— so it cannot live in `_REQUIREMENTS`, and
`test_every_operation_declares_its_capability` cannot see it. Something had to.
"""


def _created_indexes(
    operation: SnakeMigrationOperation,
) -> tuple[tuple[SnakeTableInfo, SnakeIndexInfo], ...]:
    """Every (table, index) pair this operation would create, whichever shape it carries them in."""
    if isinstance(operation, CreateIndex):
        return ((operation.table, operation.index),)
    if isinstance(operation, CreateTable):
        return tuple((operation.table, index) for index in operation.table.indexes)
    return ()


def _guard_partial_index(
    operation: SnakeMigrationOperation, dialect: SnakeDialect
) -> None:
    """Stops a partial UNIQUE index where the engine has no partial indexes, and lets a search one by.

    ONE capability, TWO behaviours, because they are not the same decision:

    - A SEARCH partial index is an OPTIMISATION. Emitting it over the whole table finds the same
      rows and stores the same bytes; what it costs is space and a little write time. That is a
      degradation of exactly the kind this catalogue exists to declare, `emit_create_index` performs
      it by dropping the `WHERE`, and the session announces the reason once.
    - A partial UNIQUE index is INTEGRITY. Widening `UNIQUE(email) WHERE deleted_at IS NULL` into
      `UNIQUE(email)` forbids rows the domain allows — re-registering a soft-deleted address stops
      working — and dropping the uniqueness instead leaves the database without a rule the model
      declares. No warning repairs either, so it stops here.

    `Cap` does not tell the two apart and should not: it describes the ENGINE, which has exactly one
    gap. What tells them apart is the index's own `unique`, already in the metadata.
    """
    if dialect.capabilities.can(Cap.PARTIAL_INDEXES):
        return
    for table, index in _created_indexes(operation):
        if index.where is None or not index.unique:
            continue
        raise SnakeMigrationError(
            f"The partial UNIQUE index '{index.resolved_name(table.name)}' of table "
            f"'{table.name}' cannot be applied: this engine has no partial indexes, so there is no "
            f"way to say 'unique only among these rows'. It is NOT degraded to a full UNIQUE the "
            f"way a search index is: that would forbid duplicates the domain allows, which is a "
            f"different schema and not a slower one. Either drop the `unique=True` (leaving the "
            f"index as a search one, which this engine does support), or express the rule with a "
            f"generated column plus a plain UNIQUE over it in a `RunSQL`."
        )


def _held_columns(
    table: SnakeTableInfo, relationship: SnakeRelationshipInfo
) -> set[tuple[str, str]]:
    """The `(table, column)` pairs this to-one foreign key HOLDS on the near side.

    The near side and not the far one: what an engine refuses to drop is the column the constraint
    is declared ON. Compound keys hold several, which is why it is a set and not one name — the
    project's rule that a simple and a compound key share one structure lands here too.
    """
    return {(table.name, local) for local, _ in relationship.foreign_key.pairs}


def _keys_removed_by(operation: RebuildTable) -> set[tuple[str, str]]:
    """The `(table, column)` pairs whose foreign key the rebuild leaves behind.

    Compared by relation NAME, which is what `foreign_key_name` derives the constraint's name from:
    the same key with another shape is still the same constraint, and the rebuild replaces it rather
    than removing it.
    """
    surviving = {
        relationship.name
        for relationship in operation.after.relationships
        if relationship.kind is SnakeRelationshipKind.TO_ONE
    }
    removed: set[tuple[str, str]] = set()
    for relationship in operation.before.relationships:
        if relationship.kind is not SnakeRelationshipKind.TO_ONE:
            continue
        if relationship.name in surviving:
            continue
        removed.update(_held_columns(operation.before, relationship))
    return removed


def _guard_dropped_fk_column(
    operation: SnakeMigrationOperation,
    dialect: SnakeDialect,
    keys_already_dropped: set[tuple[str, str]],
) -> None:
    """Stops a `DropColumn` over a column whose foreign key is still standing, where it must.

    MEASURED on the three engines, with the same statement over the same shape:

    - PostgreSQL takes it and the constraint falls with the column, so nothing is guarded here.
    - MySQL/MariaDB answer error 1553: InnoDB will not lose the index the key sits on. The way out
      is a `DropForeignKey` one operation earlier, which the ORM's own diff already emits.
    - SQLite answers "unknown column ... in foreign key definition", and it has no `DROP
      CONSTRAINT` to put in front, so the way out there is a `RebuildTable` that leaves the key
      behind — which the loop above already counts as having removed it.

    SO THE ADVICE IS PER ENGINE: telling a SQLite reader to put a `DropForeignKey` first sends them
    to an operation this very module refuses a few lines up, for lack of `Cap.ADD_CONSTRAINT`.

    It is NOT translated into an invented `DropForeignKey`. The reverse of dropping a key is adding
    it back, and that needs the target table — which this operation does not carry and must not be
    made to guess; a synthesised key would apply green and leave the rollback writing a constraint
    pointing nowhere. So the plan stops and names what is missing, in the ORM's own vocabulary.

    The guard reads the operation's OWN table: after the diff has run, the relation is gone from the
    desired table and the plan already carries the `DropForeignKey`, so it says nothing. What it
    catches is the plan written by hand — or generated somewhere the key was lost — which is the
    only place a naked drop can still reach a server.
    """
    if not isinstance(operation, DropColumn):
        return
    # `isinstance(..., Nope)` and not `not can(...)`: the two ask the same question, and this one
    # also narrows the answer to the branch that HAS a `reason`, which the MySQL message quotes.
    # Asking with `can()` would leave the reason reachable only through a cast.
    #
    # Only the MySQL branch quotes it, and that is deliberate rather than an oversight: SQLite's
    # reason ends by sending the reader to a hand-written `RunSQL`, which is the sentence this pass
    # exists to stop repeating. Quoting it under an answer that names `RebuildTable` would put the
    # two doors in one paragraph and make the reader pick. The reason itself is worth fixing where
    # it lives, in `dialects/sqlite.py`; until then this branch says the limit in its own words.
    support = dialect.capabilities.support_for(Cap.DROP_COLUMN_CASCADES_FK)
    if not isinstance(support, Nope):
        return
    for relationship in operation.table.relationships:
        if relationship.kind is not SnakeRelationshipKind.TO_ONE:
            continue
        held = _held_columns(operation.table, relationship)
        if (operation.table.name, operation.column.name) not in held:
            continue
        if held <= keys_already_dropped:
            continue
        name = foreign_key_name(operation.table, relationship)
        if dialect.capabilities.can(Cap.ADD_CONSTRAINT):
            raise SnakeMigrationError(
                f"The column '{operation.column.name}' of table '{operation.table.name}' cannot "
                f"be dropped: the foreign key '{name}' still holds it, and this engine refuses to "
                f"drop a column while its key is standing — {support.reason}. "
                f"Put a `DropForeignKey` for '{relationship.name}' BEFORE this `DropColumn`: that "
                f"is what the autodetected migration does, and it is also what makes the rollback "
                f"able to put the key back."
            )
        raise SnakeMigrationError(
            f"The column '{operation.column.name}' of table '{operation.table.name}' cannot be "
            f"dropped: the foreign key '{name}' still holds it, and this engine refuses to drop a "
            f"column that a foreign key names. A `DropForeignKey` in front does NOT open this "
            f"door — the same engine has no `ALTER TABLE ... DROP CONSTRAINT`, so that operation "
            f"is refused too, and the plan would stop in both of its halves. What works here is "
            f"remaking the table around the key: put a `RebuildTable` whose `after` no longer "
            f"carries '{relationship.name}' BEFORE this `DropColumn`, and the column comes free "
            f"with its rows intact."
        )


def _guard_capability(
    operation: SnakeMigrationOperation, dialect: SnakeDialect
) -> None:
    """Stops at the PLAN whatever the engine cannot do, saying what it is and what the way out is.

    It fails at GENERATION time (before deploying), not with a cryptic `syntax error` from the engine.
    It does NOT translate on its own initiative: rebuilding a table to simulate an `ALTER COLUMN` puts
    data at risk, and that is the user's call.
    """
    for kind, cap, reason in _REQUIREMENTS:
        if isinstance(operation, kind) and not dialect.capabilities.can(cap):
            raise SnakeMigrationError(
                f"The operation {type(operation).__name__} cannot be applied: {reason}"
            )
