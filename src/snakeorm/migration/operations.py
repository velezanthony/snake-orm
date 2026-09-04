"""Migration operations: REVERSIBLE units of schema or DATA change.

Two families: SCHEMA ones (`CreateTable`, `AddColumn`, ...) emit SQL (`up_sql`/`down_sql`) and mutate
the abstract state (`apply_to_state`); DATA ones (`RunSQL`, `RunPython`) mutate ROWS. `RunPython`
runs logic with the typed ORM (`SnakeSession`) and satisfies a separate Protocol
(`SnakeDataOperation`). The runner tells them apart by STRUCTURE (`run`/`unrun` vs
`up_sql`/`down_sql`) and runs them in the SAME transaction: the migration is atomic on Postgres even
when it mixes schema and data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from snakeorm.dialects import SnakeDialect
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakeRelationshipInfo,
    SnakeRoutineInfo,
    SnakeTableInfo,
    SnakeTriggerInfo,
)
from snakeorm.migration.ddl import (
    emit_add_check,
    emit_add_column,
    emit_add_foreign_key,
    emit_alter_column,
    emit_comments,
    emit_create_function,
    emit_create_index,
    emit_create_schema,
    emit_create_table,
    emit_create_trigger,
    emit_create_view,
    emit_drop_check,
    emit_drop_column,
    emit_drop_foreign_key,
    emit_drop_function,
    emit_drop_index,
    emit_drop_schema,
    emit_drop_table,
    emit_drop_trigger,
    emit_drop_view,
    emit_rebuild_table,
    emit_rename_column,
    emit_rename_table,
    emit_replace_view,
    emit_table_comment,
)
from snakeorm.migration.state import SchemaState

if TYPE_CHECKING:
    # Only to type `RunPython`/`SnakeDataOperation`. A lazy import: it avoids the
    # migration -> session cycle when loading the package (annotations are not evaluated at runtime).
    from snakeorm.session import SnakeSession


@runtime_checkable
class SnakeOperation(Protocol):
    """A reversible, DUAL SCHEMA operation (it emits SQL and mutates the abstract state)."""

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        """SQL to apply the operation."""
        ...

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        """SQL to undo it."""
        ...

    def apply_to_state(self, state: SchemaState) -> None:
        """Mutates the abstract state (for autogen's replay, like state_forwards in Django)."""
        ...


@runtime_checkable
class SnakeDataOperation(Protocol):
    """A DATA operation: it RUNS logic against the DB with the typed ORM (it emits no DDL).

    It runs code (migrating values, backfilling columns) with a `SnakeSession`. The runner recognises
    it by structure (`run`/`unrun`, not `up_sql`). `apply_to_state` is a no-op: it changes no schema.
    """

    def run(self, session: SnakeSession) -> None:
        """Applies the data operation forwards."""
        ...

    def unrun(self, session: SnakeSession) -> None:
        """Undoes the data operation."""
        ...

    def apply_to_state(self, state: SchemaState) -> None:
        """No-op: a data migration does not change the abstract state's tables."""
        ...


# Any operation in a migration: SCHEMA (emits SQL) or DATA (runs logic).
SnakeMigrationOperation = SnakeOperation | SnakeDataOperation


@dataclass(frozen=True, slots=True)
class CreateSchema:
    """Creates a schema; its reverse drops it. It goes BEFORE any table using it."""

    schema: str

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_create_schema(self.schema, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_schema(self.schema, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        state.add_schema(self.schema)


@dataclass(frozen=True, slots=True)
class DropSchema:
    """Drops a schema; its reverse recreates it."""

    schema: str

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_schema(self.schema, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_create_schema(self.schema, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        state.remove_schema(self.schema)


@dataclass(frozen=True, slots=True)
class CreateTable:
    """Creates a table; its reverse drops it."""

    table: SnakeTableInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        statements = [emit_create_table(self.table, dialect)]
        statements.extend(
            emit_create_index(self.table, index, dialect)
            for index in self.table.indexes
        )
        # `COMMENT ON` is a separate statement, not a CREATE TABLE clause.
        statements.extend(emit_comments(self.table, dialect))
        return statements

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [
            emit_drop_table(self.table, dialect)
        ]  # the DROP TABLE takes the indexes with it

    def apply_to_state(self, state: SchemaState) -> None:
        # Without relations: the FKs are added separately (AddForeignKey), at the end.
        state.add_table(replace(self.table, relationships=()))


@dataclass(frozen=True, slots=True)
class DropTable:
    """Drops a table; its reverse recreates it."""

    table: SnakeTableInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_table(self.table, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_create_table(self.table, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        state.remove_table(self.table.name)


@dataclass(frozen=True, slots=True)
class AddColumn:
    """Adds a column to a table; its reverse drops it."""

    table: SnakeTableInfo  # target table (for schema/name)
    column: SnakeColumnInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_add_column(self.table, self.column, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_column(self.table, self.column.name, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is not None:
            state.add_table(replace(current, columns=(*current.columns, self.column)))


@dataclass(frozen=True, slots=True)
class DropColumn:
    """Drops a column from a table; its reverse recreates it (with its original info)."""

    table: SnakeTableInfo
    column: SnakeColumnInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_column(self.table, self.column.name, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_add_column(self.table, self.column, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is not None:
            remaining = tuple(c for c in current.columns if c.name != self.column.name)
            state.add_table(replace(current, columns=remaining))


@dataclass(frozen=True, slots=True)
class RenameColumn:
    """Renames a column KEEPING its data; its reverse gives it the old name back.

    It is written BY HAND, replacing the `DropColumn` + `AddColumn` the diff generates (correct but
    catastrophic: it drops the old column along with its data).
    """

    table: SnakeTableInfo
    old_name: str
    new_name: str

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_rename_column(self.table, self.old_name, self.new_name, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_rename_column(self.table, self.new_name, self.old_name, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is None:
            return
        # Only the name changes; the rest of the definition is preserved (rebuilding the column
        # would lose whatever does not travel in this operation).
        columns = tuple(
            replace(column, name=self.new_name)
            if column.name == self.old_name
            else column
            for column in current.columns
        )
        state.add_table(replace(current, columns=columns))


def _repointed(
    table: SnakeTableInfo, old_ref: str, new_ref: str
) -> SnakeTableInfo | None:
    """The table with every relation aimed at `old_ref` re-aimed at `new_ref`, or None if none was.

    `None` and not the table itself so the caller can tell "nothing to do" from "rewritten", instead
    of putting every table in the state back through `add_table` to find out.
    """
    if not any(
        relationship.target_table == old_ref for relationship in table.relationships
    ):
        return None
    return replace(
        table,
        relationships=tuple(
            replace(relationship, target_table=new_ref)
            if relationship.target_table == old_ref
            else relationship
            for relationship in table.relationships
        ),
    )


@dataclass(frozen=True, slots=True)
class RenameTable:
    """Renames a table KEEPING its rows; its reverse gives it the old name back.

    Written BY HAND, like `RenameColumn` and for the same reason one level up: the diff sees a
    rename as `CreateTable` + `DropTable`, which is correct SQL and destroys every row in the table.
    The diff is not taught to guess it — guessing wrong keeps a table somebody asked to destroy,
    with another table's data inside.

    THE OLD NAME IS `table.name` and there is no second field holding it. Two spellings of one fact
    are two things that can disagree, and this repository has already paid for a pair broken in half
    inside the linker; here the table being renamed IS the table this operation carries, so the
    question does not arise. `RenameColumn` needs an `old_name` because a table has many columns and
    the table alone cannot say which one.

    It renames WITHIN a schema. Moving a table to another schema is `ALTER TABLE ... SET SCHEMA`, a
    different statement, and Postgres refuses to spell it as a qualified RENAME (measured).
    """

    table: SnakeTableInfo
    new_name: str

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_rename_table(self.table, self.new_name, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        # The reverse is the SAME emitter over the already-renamed table, so there is one place
        # where the statement's shape is decided and the two directions cannot drift apart.
        return [
            emit_rename_table(
                replace(self.table, name=self.new_name), self.table.name, dialect
            )
        ]

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is None:
            return
        # Read BEFORE the removal: `remove_table` purges the table's triggers, because a `DROP
        # TABLE` takes them with it. A RENAME does not — all three engines carry the trigger across
        # (Postgres hangs it off the table's OID, MariaDB moves it within the database, SQLite
        # rewrites the trigger's own reference) — so they are put back under the new name. Losing
        # them here would make the next `autodetect` emit a `CreateTrigger` for a trigger that is
        # already there; keeping the old key would emit a `DropTrigger` on a table that is gone.
        moved = [
            replace(trigger, table=self.new_name)
            for trigger in state.triggers()
            if trigger.table == current.name
        ]
        state.remove_table(current.name)
        state.add_table(replace(current, name=self.new_name))
        for trigger in moved:
            state.add_trigger(trigger)
        # The foreign keys pointing AT the table follow it on all three engines — measured:
        # Postgres tracks it by OID, MariaDB rewrites `information_schema` and SQLite rewrites the
        # `REFERENCES` clause in the other table's own DDL. So the state follows it too, or the
        # replayed schema becomes the only thing in the system still naming a table that is gone —
        # and `drop_order` and the planner both read `target_table` to work out what goes first.
        old_ref = f"{current.schema}.{current.name}"
        new_ref = f"{current.schema}.{self.new_name}"
        for table in state.tables():
            repointed = _repointed(table, old_ref, new_ref)
            if repointed is not None:
                state.add_table(repointed)


def _constraints_are_the_only_difference(
    before: SnakeTableInfo, after: SnakeTableInfo
) -> bool:
    """Whether the two snapshots agree on EVERYTHING except checks and relations.

    Derived from the metadata itself instead of listing the fields that may differ: a field added to
    `SnakeTableInfo` afterwards joins the comparison the day it appears, not the day somebody
    remembers. It is the same mechanism `_column_changed` uses one level down, and it exists for the
    same reason — the previous shape of that check was a chain of `or`s, and three fields added
    later never joined it.
    """
    return (
        replace(before, checks=after.checks, relationships=after.relationships) == after
    )


@dataclass(frozen=True, slots=True)
class RebuildTable:
    """Takes a table from one CONSTRAINT shape to another; its reverse takes it back.

    AN OPERATION AND NOT A SIDE EFFECT. SQLite has no `ALTER TABLE ADD/DROP CONSTRAINT`, so
    changing a CHECK or a foreign key means remaking the table. It is in the file, with a name and
    both snapshots, so a reader knows which table gets remade and a revert gets the other shape back.

    The file stays engine-agnostic: each dialect spells it — the minimal `ALTER` on Postgres and
    MySQL, the whole rebuild on SQLite.

    THE TWO SNAPSHOTS MAY ONLY DIFFER IN CONSTRAINTS, checked here rather than trusted. A pair
    disagreeing about a column would apply on SQLite (which recreates from `after`) and not on
    Postgres (whose minimal change emits no `ALTER COLUMN`), leaving two engines on different
    schemas without a word. Columns have their own operations; renaming has `RenameTable`.

    THE TRIGGERS RIDE IN A THIRD FIELD, and that asymmetry is forced: indexes come back because
    they live inside the snapshot, and `SnakeTableInfo` has no `triggers`. They are filled by the
    caller that holds the state (`diff_schema`) and recreated by `_remake_table`.

    THE VIEWS DO NOT TRAVEL: a trigger knows its `.table`, a view does not. The consequence is
    translated rather than hidden — SQLite's closing `ALTER TABLE ... RENAME TO` reparses the
    schema, so a standing view that READS this table fails the migration whole
    (`error in view <v>: no such table`), and `explain_rebuild_failure` turns that line into the one
    that says what to write: a `DropView` before and a `CreateView` after.
    """

    before: SnakeTableInfo
    after: SnakeTableInfo
    triggers: tuple[SnakeTriggerInfo, ...] = ()
    """The triggers hanging off this table, which the rebuild has to put back after dropping it."""

    def __post_init__(self) -> None:
        """Refuses a pair that says more than a rebuild can carry, NAMING what disagrees."""
        strangers = [
            trigger
            for trigger in self.triggers
            if (trigger.table, trigger.schema) != (self.after.name, self.after.schema)
        ]
        if strangers:
            raise SnakeMigrationError(
                f"A RebuildTable recreates the triggers of the table it remakes, and it was given "
                f"{', '.join(f'{t.name} (on {t.schema}.{t.table})' for t in strangers)} "
                f"while rebuilding '{self.after.schema}.{self.after.name}'. Nothing dropped those, "
                f"so recreating them would fail on a name that is still taken."
            )
        if (self.before.name, self.before.schema) != (
            self.after.name,
            self.after.schema,
        ):
            raise SnakeMigrationError(
                f"A RebuildTable cannot rename a table: it was given "
                f"'{self.before.schema}.{self.before.name}' as `before` and "
                f"'{self.after.schema}.{self.after.name}' as `after`. Renaming is `RenameTable`, "
                f"which keeps the rows and needs no rebuild on any of the three engines."
            )
        if _constraints_are_the_only_difference(self.before, self.after):
            return
        differing = sorted(
            field.name
            for field in fields(SnakeTableInfo)
            if field.name not in ("checks", "relationships")
            and getattr(self.before, field.name) != getattr(self.after, field.name)
        )
        raise SnakeMigrationError(
            f"A RebuildTable only changes CHECKs and foreign keys, and this pair also disagrees "
            f"about: {', '.join(differing)}. On SQLite the rebuild would apply that difference "
            f"(it recreates the table from `after`) and on Postgres it would not (the minimal "
            f"`ALTER` emits nothing for it), so the same migration would leave the two engines "
            f"with different schemas and neither would say so. Use AddColumn/DropColumn/"
            f"AlterColumn, CreateIndex/DropIndex or AlterTableComment for the rest, and leave this "
            f"operation the constraints."
        )

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return emit_rebuild_table(self.before, self.after, dialect, self.triggers)

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        # The SAME emitter with the snapshots swapped, so the two directions cannot drift: there is
        # one place where the shape of a rebuild is decided. The triggers do NOT swap: the reverse
        # drops the same table, so it owes it the same triggers back.
        return emit_rebuild_table(self.after, self.before, dialect, self.triggers)

    def apply_to_state(self, state: SchemaState) -> None:
        """Leaves the `after` snapshot in the state — and REFUSES to drop a trigger on the floor.

        THIS IS WHERE THE QUESTION CAN BE ASKED AT ALL. The operation cannot see the triggers by
        itself: `up_sql` gets a dialect and nothing else, and the file that builds it is imported
        with no state anywhere near it. `apply_to_state` is the one place a rebuild of ANY
        provenance — autodetected or written by hand — meets a `SchemaState`, and `replay` walks
        every operation of every migration through it on each `makemigrations` and each `squash`.

        So a rebuild whose table has triggers the payload does not carry stops the replay and names
        them, instead of leaving the state believing in triggers the `DROP TABLE` already ate. The
        normal path never gets here with the question open: `diff_schema` receives the state's
        triggers in the same call that builds the operation.
        """
        current = state.get_table(self.before.name)
        if current is None:
            return
        carried = {(trigger.table, trigger.name) for trigger in self.triggers}
        forgotten = [
            trigger
            for trigger in state.triggers()
            if trigger.table == current.name
            and (trigger.table, trigger.name) not in carried
        ]
        if forgotten:
            raise SnakeMigrationError(
                f"The rebuild of '{current.name}' does not carry "
                f"{', '.join(sorted(trigger.name for trigger in forgotten))}, and an engine "
                f"without ALTER TABLE ADD CONSTRAINT has to DROP the table to change a constraint "
                f"on it — which takes its triggers along, with no line in the migration saying so. "
                f"Pass them: RebuildTable(before, after, triggers=(...)). The diff fills this in "
                f"on its own; a hand-written migration has to say it."
            )
        # There is NO matching question for the views, and the asymmetry is the point: a
        # `SnakeTriggerInfo` has a `.table`, so the loop above is a fact the state answers, while
        # "which views read this table" is not a field anywhere and a `sql=` view is raw text. The
        # engine is what refuses a rebuild under a view it reads, and `explain_rebuild_failure`
        # names the two operations to write around it.
        state.add_table(self.after)
        for trigger in self.triggers:
            state.add_trigger(trigger)


@dataclass(frozen=True, slots=True)
class AlterColumn:
    """Changes an existing column (type/nullable); its reverse undoes the change."""

    table: SnakeTableInfo
    old: SnakeColumnInfo
    new: SnakeColumnInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return emit_alter_column(self.table, self.old, self.new, dialect)

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return emit_alter_column(self.table, self.new, self.old, dialect)

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is not None:
            columns = tuple(
                self.new if column.name == self.new.name else column
                for column in current.columns
            )
            state.add_table(replace(current, columns=columns))


@dataclass(frozen=True, slots=True)
class AlterTableComment:
    """Changes an existing table's `COMMENT ON TABLE`; its reverse restores the previous one.

    The COLUMN one is already covered by `AlterColumn`; this is the TABLE one. On an engine without
    comments (SQLite) up/down come out empty: the operation exists in the history but emits nothing.
    """

    table: SnakeTableInfo  # with the NEW db_comment
    previous: str | None  # the previous db_comment, for the reverse

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        if not dialect.supports_comments:
            return []
        return [emit_table_comment(self.table, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        if not dialect.supports_comments:
            return []
        return [
            emit_table_comment(replace(self.table, db_comment=self.previous), dialect)
        ]

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is not None:
            state.add_table(replace(current, db_comment=self.table.db_comment))


@dataclass(frozen=True, slots=True)
class AddCheck:
    """Adds a CHECK constraint to an ALREADY existing table; its reverse drops it.

    A NEW table's checks are emitted by its own `CreateTable`, just as its indexes are.
    """

    table: SnakeTableInfo
    check: SnakeCheckInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_add_check(self.table, self.check, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_check(self.table, self.check, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is not None:
            state.add_table(replace(current, checks=(*current.checks, self.check)))


@dataclass(frozen=True, slots=True)
class DropCheck:
    """Drops a CHECK constraint; its reverse recreates it with its original condition."""

    table: SnakeTableInfo
    check: SnakeCheckInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_check(self.table, self.check, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_add_check(self.table, self.check, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is None:
            return
        dropped = self.check.resolved_name(current.name)
        remaining = tuple(
            check
            for check in current.checks
            if check.resolved_name(current.name) != dropped
        )
        state.add_table(replace(current, checks=remaining))


@dataclass(frozen=True, slots=True)
class CreateIndex:
    """Creates an index on an ALREADY existing table; its reverse drops it.

    It only appears when the table is already in the state: a NEW table's indexes are emitted by
    `CreateTable.up_sql` itself, and duplicating them here would make the migration fail on apply.
    """

    table: SnakeTableInfo
    index: SnakeIndexInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_create_index(self.table, self.index, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_index(self.table, self.index, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is not None:
            state.add_table(replace(current, indexes=(*current.indexes, self.index)))


@dataclass(frozen=True, slots=True)
class DropIndex:
    """Drops an index; its reverse recreates it (with its original info: columns, unique, name)."""

    table: SnakeTableInfo
    index: SnakeIndexInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_index(self.table, self.index, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_create_index(self.table, self.index, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is None:
            return
        # Compared by RESOLVED NAME: that is the index's identity in the DB, and two indexes with
        # the same columns but different names are different indexes.
        dropped = self.index.resolved_name(current.name)
        remaining = tuple(
            index
            for index in current.indexes
            if index.resolved_name(current.name) != dropped
        )
        state.add_table(replace(current, indexes=remaining))


@dataclass(frozen=True, slots=True)
class AddForeignKey:
    """Adds an FK (at the end, after the tables are created); its reverse drops it."""

    table: SnakeTableInfo  # source table
    relationship: SnakeRelationshipInfo
    target: SnakeTableInfo  # target table already resolved

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [
            emit_add_foreign_key(self.table, self.relationship, self.target, dialect)
        ]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_foreign_key(self.table, self.relationship, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is not None:
            state.add_table(
                replace(
                    current, relationships=(*current.relationships, self.relationship)
                )
            )


@dataclass(frozen=True, slots=True)
class DropForeignKey:
    """Drops an FK; its reverse recreates it (with the original target table)."""

    table: SnakeTableInfo
    relationship: SnakeRelationshipInfo
    target: SnakeTableInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_foreign_key(self.table, self.relationship, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [
            emit_add_foreign_key(self.table, self.relationship, self.target, dialect)
        ]

    def apply_to_state(self, state: SchemaState) -> None:
        current = state.get_table(self.table.name)
        if current is not None:
            remaining = tuple(
                r for r in current.relationships if r.name != self.relationship.name
            )
            state.add_table(replace(current, relationships=remaining))


# -- VIEW operations (CREATE/ALTER/DROP VIEW) -----------------------------------------------
#
# A view is READ-ONLY and depends on the tables: it is created AFTER them. It emits no FK; if its
# definition changes the whole thing is REPLACED (there is no AddColumn/AlterColumn for a view).


@dataclass(frozen=True, slots=True)
class CreateView:
    """Creates a view (`CREATE VIEW ... AS <def>`); its reverse drops it."""

    view: SnakeTableInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_create_view(self.view, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_view(self.view, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        # The view enters the state marked as such (no relations: they are navigation, not real FK).
        state.add_table(replace(self.view, relationships=()))


@dataclass(frozen=True, slots=True)
class DropView:
    """Drops a view (`DROP VIEW`); its reverse recreates it with its original definition."""

    view: SnakeTableInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_view(self.view, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_create_view(self.view, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        state.remove_table(self.view.name)


@dataclass(frozen=True, slots=True)
class AlterView:
    """Changes a view's definition; its reverse restores the old one.

    A changed FILTER is a `CREATE OR REPLACE VIEW`. A changed PROJECTION is not: no engine's
    replacement can rename an output column — measured on PostgreSQL, `cannot change name of view
    column "a" to "x"` — so the view has to be dropped and made again.

    That is decided by comparing the two column lists and NOT by asking the dialect what it supports,
    because it is not a capability question. PostgreSQL and MySQL both declare `Cap.REPLACE_VIEW` and
    both refuse this: `Cap` answers "can this engine do X", and what is being asked here is "can X
    express the change". The two agreed until a view's projection moved.
    """

    old: SnakeTableInfo
    new: SnakeTableInfo

    def _projection_changed(self) -> bool:
        """Whether the output columns differ in NAME or in ORDER. A view's columns are positional."""
        return tuple(column.name for column in self.old.columns) != tuple(
            column.name for column in self.new.columns
        )

    def _rebuild(self, target: SnakeTableInfo, dialect: SnakeDialect) -> list[str]:
        """Drop and create, which is what a changed projection requires on every engine."""
        return [emit_drop_view(target, dialect), emit_create_view(target, dialect)]

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        if self._projection_changed():
            return self._rebuild(self.new, dialect)
        return [emit_replace_view(self.new, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        if self._projection_changed():
            return self._rebuild(self.old, dialect)
        return [emit_replace_view(self.old, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        state.add_table(replace(self.new, relationships=()))


# -- ROUTINE operations (stored functions/procedures) ---------------------------------------
#
# A routine is OPAQUE SQL: its `body` is the complete `CREATE OR REPLACE FUNCTION ...`, raw and NOT
# portable. If it changes the whole thing is REPLACED (AlterFunction, via CREATE OR REPLACE); the
# reverse of creating is DROP FUNCTION. Autodetect diffs them by comparing the desired `body` with
# the history's. They are created AFTER tables and views (they may depend on them) and are not
# ordered among themselves.


@dataclass(frozen=True, slots=True)
class CreateFunction:
    """Creates (or replaces) a routine by emitting its `body`; its reverse drops it (DROP FUNCTION)."""

    definition: SnakeRoutineInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_create_function(self.definition, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_function(self.definition, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        state.add_routine(self.definition)


@dataclass(frozen=True, slots=True)
class DropFunction:
    """Drops a routine (DROP FUNCTION); its reverse recreates it with its original `body`."""

    definition: SnakeRoutineInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_drop_function(self.definition, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_create_function(self.definition, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        state.remove_routine(self.definition.name)


@dataclass(frozen=True, slots=True)
class AlterFunction:
    """Changes a routine (CREATE OR REPLACE with the new `body`); its reverse restores the old one."""

    old: SnakeRoutineInfo
    new: SnakeRoutineInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_create_function(self.new, dialect)]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        return [emit_create_function(self.old, dialect)]

    def apply_to_state(self, state: SchemaState) -> None:
        state.add_routine(self.new)


# -- DATA operations (they mutate rows, not tables) -----------------------------------------


def _as_statements(sql: str | tuple[str, ...]) -> list[str]:
    """Normalises `RunSQL`'s `up`/`down`: a `str` is ONE statement; a tuple, several."""
    if isinstance(sql, str):
        return [sql]
    return list(sql)


@dataclass(frozen=True, slots=True)
class RunSQL:
    """RAW data SQL: it runs `up`'s statements, and `down`'s as the reverse (or nothing).

    An escape hatch: bare SQL, NOT portable between engines. It fits `SnakeOperation` (it emits SQL)
    but it is a DATA migration: `apply_to_state` is a no-op (it mutates rows, not the abstract schema).
    """

    up: str | tuple[str, ...]
    down: str | tuple[str, ...] | None = None

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        """`up`'s statements (raw: the dialect does not touch them)."""
        return _as_statements(self.up)

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        """`down`'s statements, or `[]` if no reverse was declared."""
        return [] if self.down is None else _as_statements(self.down)

    def apply_to_state(self, state: SchemaState) -> None:
        """No-op: a data migration does not change the abstract state's tables."""
        return None


@dataclass(frozen=True, slots=True)
class RunPython:
    """A DATA operation running Python code with the typed ORM (a `SnakeSession`).

    `forward`/`backward` receive a `SnakeSession` and migrate data with the ORM. They MUST be
    module-level functions (importable), not lambdas or closures: the renderer writes them by
    reference. Without `backward` the migration is not reversible and `unrun` says so plainly.
    """

    forward: Callable[[SnakeSession], None]
    backward: Callable[[SnakeSession], None] | None = None

    def run(self, session: SnakeSession) -> None:
        """Applies the data migration: it invokes `forward` with the session."""
        self.forward(session)

    def unrun(self, session: SnakeSession) -> None:
        """Undoes the data migration with `backward`; without it, raises `SnakeMigrationError`."""
        if self.backward is None:
            raise SnakeMigrationError(
                "This RunPython does not declare `backward`: the data migration is not "
                "reversible. Add a module-level backward(session) function if you need the rollback."
            )
        self.backward(session)

    def apply_to_state(self, state: SchemaState) -> None:
        """No-op: a data migration does not change the abstract state's tables."""
        return None


@dataclass(frozen=True, slots=True)
class CreateTrigger:
    """Creates a trigger. Its inverse is dropping it."""

    definition: SnakeTriggerInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        """`CREATE TRIGGER ...`."""
        return emit_create_trigger(self.definition, dialect)

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        """`DROP TRIGGER ...`."""
        return emit_drop_trigger(self.definition, dialect)

    def apply_to_state(self, state: SchemaState) -> None:
        """Adds the trigger to the replayed state."""
        state.add_trigger(self.definition)


@dataclass(frozen=True, slots=True)
class DropTrigger:
    """Drops a trigger. Its inverse is creating it again."""

    definition: SnakeTriggerInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        """`DROP TRIGGER ...`."""
        return emit_drop_trigger(self.definition, dialect)

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        """`CREATE TRIGGER ...`."""
        return emit_create_trigger(self.definition, dialect)

    def apply_to_state(self, state: SchemaState) -> None:
        """Removes the trigger from the replayed state."""
        state.remove_trigger(self.definition.table, self.definition.name)


@dataclass(frozen=True, slots=True)
class AlterTrigger:
    """Replaces a trigger: it is DROPPED and created again.

    With no portable `CREATE OR REPLACE TRIGGER`, it is done in two steps. The `down` recreates the
    OLD one, so undoing gives back exactly the trigger that was there.
    """

    old: SnakeTriggerInfo
    new: SnakeTriggerInfo

    def up_sql(self, dialect: SnakeDialect) -> list[str]:
        """Drops the old one and creates the new one."""
        return [
            *emit_drop_trigger(self.old, dialect),
            *emit_create_trigger(self.new, dialect),
        ]

    def down_sql(self, dialect: SnakeDialect) -> list[str]:
        """Drops the new one and restores the old one."""
        return [
            *emit_drop_trigger(self.new, dialect),
            *emit_create_trigger(self.old, dialect),
        ]

    def apply_to_state(self, state: SchemaState) -> None:
        """Leaves the NEW trigger in the replayed state."""
        state.add_trigger(self.new)
