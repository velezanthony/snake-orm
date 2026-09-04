"""Diff engine (autodetection): two schema states -> migration operations.

The heart of the CODE-FIRST flow. Agnostic about where the previous state came from (snapshot /
replay / reflection): it receives two collections of SnakeTableInfo. Order: tables and columns first
and the FKs LAST (so every table exists before any FK, with no topological ordering); FKs are only
diffed if `resolve_target` is passed. It also detects changes inside a column (-> AlterColumn) and
the indexes of an already existing table (a new table's are emitted by `CreateTable`).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from typing import get_origin

from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.migration.ddl import topological_view_order, view_fingerprint
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeRoutineInfo,
    SnakeTableInfo,
    SnakeTriggerInfo,
)
from snakeorm.migration.operations import (
    AddCheck,
    AddColumn,
    AddForeignKey,
    AlterColumn,
    AlterFunction,
    AlterTableComment,
    AlterTrigger,
    AlterView,
    CreateFunction,
    CreateIndex,
    CreateSchema,
    CreateTable,
    CreateTrigger,
    CreateView,
    DropCheck,
    DropColumn,
    DropForeignKey,
    DropFunction,
    DropIndex,
    DropTable,
    DropTrigger,
    DropView,
    RebuildTable,
    SnakeOperation,
)
from snakeorm.sql.condition import emit_condition_ddl

ResolveTarget = Callable[[str], SnakeTableInfo | None]


def diff_schema(
    before: Iterable[SnakeTableInfo],
    after: Iterable[SnakeTableInfo],
    resolve_target: ResolveTarget | None = None,
    resolve_qualified: ResolveTarget | None = None,
    triggers: Iterable[SnakeTriggerInfo] = (),
) -> list[SnakeOperation]:
    """Derives the operations to get from schema `before` to `after`.

    Order: tables (create/drop/columns) -> FKs -> views (which depend on the tables). Views are not
    mixed in with columns or FKs; if their definition changes the whole thing is replaced (AlterView).

    `triggers` are the ones the schema ALREADY has — the replayed state's, which is the only place
    that knows they exist, since `SnakeTableInfo` has no field for one. They are not diffed here
    (`diff_triggers` does that, afterwards): they are handed to any `RebuildTable` this call emits,
    because on an engine with no `ALTER TABLE ADD CONSTRAINT` that rebuild DROPS the table and takes
    them with it. Filling them in the same call that builds the operation is what keeps a rebuild
    from coming out headless — nobody has to remember a second step.

    THE VIEWS ARE NOT HANDED OVER, and the difference from the triggers is a fact against a guess.
    A `SnakeTriggerInfo` has a `.table`, so "the triggers of this table" is a question the state
    answers exactly. Nothing says which TABLES a view reads: `depends_on` is view->view only and is
    refused for tables on purpose, and a view declared with `sql=` is raw text. So the generator
    emits the rebuild bare: the engine refuses it, the migration rolls back whole, and
    `explain_rebuild_failure` says to put a `DropView` before it and a `CreateView` after it.
    """
    before_list = list(before)
    after_list = list(after)
    before_tables = [table for table in before_list if not table.is_view]
    after_tables = [table for table in after_list if not table.is_view]
    # Keyed by (SCHEMA, name) and not by name. `@snake_model(schema=...)` makes `public.events` and
    # `analytics.events` a legal pair, and a dict keyed by the bare name let the second overwrite the
    # first: `diff_schema([], [public, analytics])` emitted ONE CreateTable, so the other table was
    # never created and nothing said so. The mirror case is worse — moving a table between schemas
    # looked like no change, so the migration came out empty and regenerated identically forever.
    before_by_name = {(table.schema, table.name): table for table in before_tables}
    after_by_name = {(table.schema, table.name): table for table in after_tables}
    triggers_by_table: dict[tuple[str, str], list[SnakeTriggerInfo]] = {}
    for trigger in triggers:
        triggers_by_table.setdefault((trigger.schema, trigger.table), []).append(
            trigger
        )

    # Schemas come FIRST: a table in `analytics` cannot be created if `analytics` does not exist.
    # It is the same ordering criterion as the FKs going last, from the opposite side.
    schema_ops: list[SnakeOperation] = _diff_schemas(before_list, after_list)

    # The FKs are diffed FIRST, before the per-table loop, and that is new: the loop has to be able
    # to tell whether a table's ONLY change is to its constraints, and half of the constraints live
    # here. The order they are EMITTED in has not moved.
    key_ops: list[AddForeignKey | DropForeignKey] = []
    if resolve_target is not None:
        key_ops = _diff_foreign_keys(
            before_by_name, after_tables, resolve_target, resolve_qualified
        )
    keys_changed = {(op.table.schema, op.table.name) for op in key_ops}

    table_ops: list[SnakeOperation] = []
    rebuilds: list[SnakeOperation] = []
    rebuilt: set[tuple[str, str]] = set()
    for name in sorted(after_by_name):
        if name in before_by_name:
            before_t, after_t = before_by_name[name], after_by_name[name]
            # Indexes are DROPPED before touching the columns and CREATED after: see _diff_indexes.
            index_drops, index_creates = _diff_indexes(before_t, after_t)
            check_drops, check_adds = _diff_checks(before_t, after_t)
            column_ops = _diff_columns(before_t, after_t)
            comment_changed = before_t.db_comment != after_t.db_comment
            if _is_a_pure_constraint_change(
                checks_changed=bool(check_drops or check_adds),
                keys_changed=name in keys_changed,
                other_changes=bool(index_drops or index_creates or column_ops)
                or comment_changed,
            ):
                rebuilt.add(name)
                rebuilds.append(
                    RebuildTable(
                        before_t,
                        _constraint_shape(
                            before_t, after_t, keys_diffed=resolve_target is not None
                        ),
                        triggers=tuple(triggers_by_table.get(name, ())),
                    )
                )
                continue
            table_ops.extend(check_drops)
            table_ops.extend(index_drops)
            table_ops.extend(column_ops)
            table_ops.extend(index_creates)
            table_ops.extend(check_adds)
            if comment_changed:
                # The COLUMN comment is already diffed by `_column_changed`; the TABLE one was forgotten.
                table_ops.append(
                    AlterTableComment(after_t, previous=before_t.db_comment)
                )
        else:
            # New table: its indexes are emitted by CreateTable.up_sql itself, not a CreateIndex.
            table_ops.append(CreateTable(after_by_name[name]))
    drop_ops: list[SnakeOperation] = [
        DropTable(table)
        for table in drop_order(
            [
                before_by_name[name]
                for name in sorted(before_by_name)
                if name not in after_by_name
            ]
        )
    ]

    # FK DROPS go BEFORE the columns and the ADDS after, the same ordering the indexes and the
    # CHECKs above already follow — and for the same reason, measured against Postgres: dropping a
    # column takes its constraint with it, so a `DROP CONSTRAINT` emitted afterwards answers
    # `UndefinedObject: constraint ... does not exist` and the migration aborts. Removing a
    # relationship from a model used to produce a file that could not be applied.
    fk_drops: list[SnakeOperation] = []
    fk_adds: list[SnakeOperation] = []
    for operation in key_ops:
        if (operation.table.schema, operation.table.name) in rebuilt:
            continue  # its rebuild carries the key: emitting it too would apply it twice
        target = fk_drops if isinstance(operation, DropForeignKey) else fk_adds
        target.append(operation)

    view_ops = _diff_views(before_list, after_list)

    # The rebuilds sit BETWEEN the creations and the drops, and the slot is not decoration: a
    # rebuild carries its table's foreign keys, so every table it points at has to exist already
    # (hence after the CreateTables) and every table it stops pointing at must still be there
    # (hence before the DropTables).
    return [
        *schema_ops,
        *fk_drops,
        *table_ops,
        *rebuilds,
        *drop_ops,
        *fk_adds,
        *view_ops,
    ]


def _is_a_pure_constraint_change(
    *, checks_changed: bool, keys_changed: bool, other_changes: bool
) -> bool:
    """Whether this table's whole difference is CHECKs and foreign keys, and nothing else.

    THE SECOND HALF IS THE IMPORTANT ONE. A rebuild that also swallowed the column operations would
    take `rename_suggestions` down with it: the warning that stops a `DropColumn` + `AddColumn` pair
    from deleting a column's data reads exactly those two operations out of the diff, and so does
    `narrowing_warnings` with `AlterColumn`. Going quiet there — on tables that have constraints,
    which is to say the ones with rules worth keeping — is a net that fails open, and this branch
    has already deleted three of those for doing precisely that.

    So the collapse happens only where there is nothing else to hide: no column moved, no index
    moved, no comment moved. What is left is a change SQLite can make no other way than by remaking
    the table, and that is what the operation is called.
    """
    return (checks_changed or keys_changed) and not other_changes


def _constraint_shape(
    before: SnakeTableInfo, after: SnakeTableInfo, *, keys_diffed: bool
) -> SnakeTableInfo:
    """The `after` snapshot of a rebuild: the table as it IS, wearing the constraints it SHOULD have.

    Built from `before` and not from the desired table on purpose. The two agree on everything the
    diff compares, but not necessarily on everything they CARRY — `_NOT_A_COLUMN_CHANGE` lists the
    column fields that deliberately change nothing in SQL, and a snapshot that differed in one of
    them would be refused by `RebuildTable` for a difference no engine can see. What goes into the
    file is the shape the database really has, plus the constraints that are the point of the file.

    Only to-one relations travel: a to-many is the inverse and its key lives on the other table, the
    same filter `_diff_foreign_keys` applies. With no `resolve_target` the keys were never diffed at
    all, so the previous ones are kept rather than invented.
    """
    relationships = (
        tuple(
            relationship
            for relationship in after.relationships
            if relationship.kind is SnakeRelationshipKind.TO_ONE
        )
        if keys_diffed
        else before.relationships
    )
    return dataclasses.replace(before, checks=after.checks, relationships=relationships)


def drop_order(tables: list[SnakeTableInfo]) -> list[SnakeTableInfo]:
    """Orders tables so the one HOLDING a foreign key is dropped before the one it points at.

    Two of the three engines refuse `DROP TABLE` while a key points at the table — measured:
    PostgreSQL says other objects depend on it, MariaDB answers error 1451, and only SQLite accepts
    it and leaves the key dangling. It is not a dialect difference to translate in the emitter: the
    SQL is correct and what matters is the ORDER.

    It is the exact mirror of the creation order the planner already derives from the same FKs, and
    of `topological_view_order`, which drops views in reverse of the order it creates them in.

    Only edges INSIDE this set count: a key into a table that is not being dropped constrains
    nothing here. A table pointing at ITSELF (`parent_id`, the commonest tree there is) imposes no
    order either — its own edge cannot make it wait for itself. A real cycle between two tables
    cannot be ordered at all, so it stops and names THE WHOLE LOOP: naming one end sends the reader
    to look at half of it, and the half they cannot see is the one holding the other key.
    """
    by_name = {table.name: table for table in tables}
    ordered: list[SnakeTableInfo] = []
    visited: set[str] = set()
    # A LIST and not a set, unlike the view ordering: the message quotes the loop, and a set has no
    # loop in it — only the names that happen to be in flight.
    path: list[str] = []

    def visit(table: SnakeTableInfo) -> None:
        """Emits everything that points AT this table before emitting the table itself."""
        if table.name in visited:
            return
        if table.name in path:
            loop = [*path[path.index(table.name) :], table.name]
            raise SnakeMigrationError(
                f"Cycle of foreign keys among the tables being dropped: "
                f"{' -> '.join(loop)}. There is no order in which they can be retired — whichever "
                f"goes first, a key from the next one is still pointing at it. Break the loop with "
                f"an explicit `DropForeignKey` before the drops."
            )
        path.append(table.name)
        for holder in sorted(by_name.values(), key=lambda item: item.name):
            if holder.name != table.name and table.name in _referenced_tables(holder):
                visit(holder)
        path.pop()
        visited.add(table.name)
        ordered.append(table)

    for table in sorted(tables, key=lambda item: item.name):
        visit(table)
    return ordered


def _referenced_tables(table: SnakeTableInfo) -> set[str]:
    """The bare names of the tables this table's to-one keys POINT AT.

    Only TO_ONE: a to-many is the inverse relation and its constraint lives on the other table, so
    counting it would invent an edge in the wrong direction — the same filter `planner._referenced`
    applies, and for the same reason.
    """
    return {
        relationship.target_table.rpartition(".")[2]
        for relationship in table.relationships
        if relationship.kind is SnakeRelationshipKind.TO_ONE
        and relationship.target_table
    }


def _diff_schemas(
    before: list[SnakeTableInfo], after: list[SnakeTableInfo]
) -> list[SnakeOperation]:
    """Schemas that are needed and do not exist yet -> `CreateSchema`.

    `public` is never created (it always exists in Postgres). No `DropSchema` is emitted when one
    empties out: it may hold things we do not govern; cleaning up is the human's call.
    """
    known = {table.schema for table in before} | {DEFAULT_SCHEMA}
    needed = {table.schema for table in after}
    return [CreateSchema(schema) for schema in sorted(needed - known)]


def _bare_view(view: SnakeTableInfo) -> SnakeTableInfo:
    """A view stripped of relations for the operations: its FKs are navigation, not real constraints.

    It keeps `depends_on`: the topological order (create/drop) and the render round-trip both use it.
    """
    return dataclasses.replace(view, relationships=())


def _diff_views(
    before: list[SnakeTableInfo], after: list[SnakeTableInfo]
) -> list[SnakeOperation]:
    """Compares both states' views: new -> CreateView, dropped -> DropView, def changed -> AlterView.

    The CreateViews are ordered topologically (a view after those it depends on, `depends_on`); the
    DropViews in REVERSE order (the depending one first). AlterView (CREATE OR REPLACE) is not
    ordered: both views already exist. A cycle between views raises `SnakeMigrationError`.
    """
    before_by_name = {view.name: view for view in before if view.is_view}
    after_by_name = {view.name: view for view in after if view.is_view}

    to_create: list[SnakeTableInfo] = []
    alters: list[SnakeOperation] = []
    for name in sorted(after_by_name):
        after_view = after_by_name[name]
        before_view = before_by_name.get(name)
        if before_view is None:
            to_create.append(after_view)
        elif view_fingerprint(before_view) != view_fingerprint(after_view):
            # By FINGERPRINT and not by `view_definition`: a view declared with `query=` no longer
            # holds a string — it holds the uncompiled query, so each engine writes its own body —
            # so comparing the field directly would always report "no changes".
            alters.append(AlterView(_bare_view(before_view), _bare_view(after_view)))
    to_drop = [
        before_by_name[name]
        for name in sorted(before_by_name)
        if name not in after_by_name
    ]

    create_ops: list[SnakeOperation] = [
        CreateView(_bare_view(view)) for view in topological_view_order(to_create)
    ]
    drop_ops: list[SnakeOperation] = [
        DropView(_bare_view(view)) for view in reversed(topological_view_order(to_drop))
    ]
    return [*create_ops, *alters, *drop_ops]


def diff_routines(
    before: Iterable[SnakeRoutineInfo], after: Iterable[SnakeRoutineInfo]
) -> list[SnakeOperation]:
    """Compares the desired routines (functions) against the history -> migration operations.

    Like a table, but a routine is OPAQUE: only the `body` string is compared. New -> CreateFunction;
    body changed -> AlterFunction(old, new); removed -> DropFunction. The key is the `name`
    (consistent with `SchemaState`, which indexes routines by name). Functions are emitted AFTER
    tables and views (they may depend on them); they are not ordered among themselves (a documented
    limitation).
    """
    before_by_name = {routine.name: routine for routine in before}
    after_by_name = {routine.name: routine for routine in after}

    operations: list[SnakeOperation] = []
    for name in sorted(after_by_name):
        after_routine = after_by_name[name]
        before_routine = before_by_name.get(name)
        if before_routine is None:
            operations.append(CreateFunction(after_routine))
        elif before_routine.body != after_routine.body:
            operations.append(AlterFunction(before_routine, after_routine))
    for name in sorted(before_by_name):
        if name not in after_by_name:
            operations.append(DropFunction(before_by_name[name]))
    return operations


def diff_triggers(
    before: Iterable[SnakeTriggerInfo], after: Iterable[SnakeTriggerInfo]
) -> list[SnakeOperation]:
    """Compares the desired triggers against the history -> migration operations.

    Like `diff_routines`, but the key is `(table, name)`: in Postgres two tables can each have a
    trigger of the same name, and indexing by name would silently overwrite one. ALL fields are
    compared (timing and events count too); with no portable `CREATE OR REPLACE TRIGGER`, any change
    is a DROP + CREATE (`AlterTrigger`).
    """
    before_by_key = {(t.table, t.name): t for t in before}
    after_by_key = {(t.table, t.name): t for t in after}

    operations: list[SnakeOperation] = []
    for key in sorted(after_by_key):
        new = after_by_key[key]
        old = before_by_key.get(key)
        if old is None:
            operations.append(CreateTrigger(new))
        elif old != new:
            operations.append(AlterTrigger(old, new))
    for key in sorted(before_by_key):
        if key not in after_by_key:
            operations.append(DropTrigger(before_by_key[key]))
    return operations


def _diff_columns(
    before: SnakeTableInfo, after: SnakeTableInfo
) -> list[SnakeOperation]:
    """Compares the columns of a table existing in both states -> Add/Drop column."""
    before_columns = {column.name: column for column in before.columns}
    after_columns = {column.name: column for column in after.columns}

    operations: list[SnakeOperation] = []
    for name in sorted(after_columns):
        if name not in before_columns:
            operations.append(AddColumn(after, after_columns[name]))
        elif _column_changed(before_columns[name], after_columns[name]):
            operations.append(
                AlterColumn(after, before_columns[name], after_columns[name])
            )
    for name in sorted(before_columns):
        if name not in after_columns:
            operations.append(DropColumn(after, before_columns[name]))
    return operations


_NOT_A_COLUMN_CHANGE: dict[str, str] = {
    "name": "the diff KEYS by it; a different name is a different column (or a RenameColumn)",
    "attr_name": "Python-side only: what the attribute is called changes no SQL",
    "index": "diffed apart by `_diff_indexes`, because indexes are dropped before the column "
    "changes and created after",
    "default_factory": "a callable, and two equivalent lambdas are never `==`: comparing it "
    "would emit a migration on every single run",
    "type_params": "compared through the properties it feeds (precision, scale, int_size, "
    "max_length, json_storage), which NORMALISE — `None` and the explicit default mean the "
    "same type, and comparing the raw params would invent changes that are not there",
    "python_type": "compared through `_comparable_type`, which normalises the one case where the "
    "parameters provably do not reach SQL: raw identity made `dict` -> `dict[str, object]` an "
    "AlterColumn that every dialect then rendered as no statements at all",
}
"""Fields of `SnakeColumnInfo` the diff deliberately does not compare, each with its reason.

An OPT-OUT with a written reason instead of an opt-in by memory. The comparison used to be a chain
of thirteen `or`s, and a field added to `SnakeColumnInfo` afterwards simply never joined it:
`autoincrement`, `enum_type` and `enum_storage` were all invisible, so `BIGINT` -> `BIGSERIAL` and
any change to an enum produced an EMPTY migration — no error, and a `makemigrations` that goes on
proposing nothing while the model and the database drift.

`test_column_diff.py` fails if a field is neither compared nor listed here, which is the same
mechanism as the `Cap` catalogue: you cannot forget to answer, only answer explicitly.
"""


def _column_changed(old: SnakeColumnInfo, new: SnakeColumnInfo) -> bool:
    """Whether a column changed in anything the schema can tell apart.

    Derived from `SnakeColumnInfo`'s own fields minus `_NOT_A_COLUMN_CHANGE`, so a field added to
    the metadata is compared the day it appears rather than the day somebody remembers.
    """
    for field in dataclasses.fields(SnakeColumnInfo):
        if field.name in _NOT_A_COLUMN_CHANGE:
            continue
        if getattr(old, field.name) != getattr(new, field.name):
            return True
    # Fed by `type_params`, which is excluded above: these properties normalise it, so they are the
    # comparable face of it. Widening an int (INTEGER->BIGINT), a VARCHAR(100)->VARCHAR(255) and a
    # JSONB<->JSON all live here and all change the real column type.
    return (
        old.precision != new.precision
        or old.scale != new.scale
        or old.int_size != new.int_size
        or old.max_length != new.max_length
        or old.json_storage != new.json_storage
        or _comparable_type(old.python_type) != _comparable_type(new.python_type)
    )


def _comparable_type(python_type: type) -> object:
    """The face of a `python_type` that the SCHEMA can tell apart.

    A `dict` is ONE opaque JSON value in all three engines, so how it is parameterised never reaches
    SQL. Compared by identity, refining `SnakeColumn[dict]` into `SnakeColumn[dict[str, object]]`
    produced an `AlterColumn` that `emit_alter_column` then rendered as no statements at all — an
    operation asking for `ALTER COLUMN ... TYPE JSONB` on a column that is already JSONB, which on
    Postgres is a full table rewrite under a lock to change nothing. Demanding an outage because
    somebody typed their `dict` properly punishes the one rule this project cares most about, and it
    happened here: to these demos, the day that annotation was fixed.

    It is NOT a blanket unwrap of the origin, which is the fix that looks obvious and is wrong.
    Measured on Postgres, `list[int]` is `BIGINT[]` and `list[str]` is `TEXT[]`: comparing origins
    would call those one column and lose a real change. This one is loud and that one would be
    silent, so the normalisation stays narrow and stays measured — `test_the_diff_compares_what_
    reaches_sql` asserts BOTH halves, so the day an engine spells the two dicts differently it goes
    red instead of quietly under-reporting.
    """
    return dict if get_origin(python_type) is dict else python_type


def _diff_checks(
    before: SnakeTableInfo, after: SnakeTableInfo
) -> tuple[list[SnakeOperation], list[SnakeOperation]]:
    """Compares the CHECKs of a table present in BOTH states -> (dropped, added).

    Two lists because of ordering (as with indexes): a CHECK is dropped BEFORE touching the columns
    and added AFTER. Identity = resolved name; if the condition changes under the same name it is
    recreated (in SQL a CHECK is not altered in place). Comparison is by the emitted SQL, not by
    object identity (the AST nodes use `eq=False`).
    """
    dialect = PostgresDialect()

    def fingerprint(check: SnakeCheckInfo) -> str:
        """A CHECK's comparable fingerprint: its already-emitted SQL."""
        return emit_condition_ddl(check.condition, dialect)

    before_by_name = {
        check.resolved_name(before.name): check for check in before.checks
    }
    after_by_name = {check.resolved_name(after.name): check for check in after.checks}

    drops: list[SnakeOperation] = [
        DropCheck(before, check)
        for name, check in sorted(before_by_name.items(), key=lambda item: item[0])
        if name not in after_by_name
        or fingerprint(after_by_name[name]) != fingerprint(check)
    ]
    adds: list[SnakeOperation] = [
        AddCheck(after, check)
        for name, check in sorted(after_by_name.items(), key=lambda item: item[0])
        if name not in before_by_name
        or fingerprint(before_by_name[name]) != fingerprint(check)
    ]
    return drops, adds


def _diff_indexes(
    before: SnakeTableInfo, after: SnakeTableInfo
) -> tuple[list[SnakeOperation], list[SnakeOperation]]:
    """Compares the indexes of a table existing in BOTH states -> (dropped, created).

    Two separate lists because of ordering: an index is DROPPED before touching the columns and
    CREATED after. Identity = resolved name; if anything else changes (columns, unique) it is
    recreated (in SQL an index is not altered in place).
    """
    dialect = PostgresDialect()

    def fingerprint(index: SnakeIndexInfo) -> tuple[object, ...]:
        """An index's comparable fingerprint.

        The `where` is compared by the SQL it emits, not with `==`: the AST nodes use `eq=False` and
        two equivalent conditions would be different objects, a phantom change on every pass.
        """
        where = (
            emit_condition_ddl(index.where, dialect)
            if index.where is not None
            else None
        )
        return (index.columns, index.unique, index.method, where)

    before_by_name = {
        index.resolved_name(before.name): index for index in before.indexes
    }
    after_by_name = {index.resolved_name(after.name): index for index in after.indexes}

    def changed(
        name: str, index: SnakeIndexInfo, other: dict[str, SnakeIndexInfo]
    ) -> bool:
        """Whether the index is absent from the other state, or present with another definition."""
        counterpart = other.get(name)
        return counterpart is None or fingerprint(counterpart) != fingerprint(index)

    drops: list[SnakeOperation] = [
        DropIndex(before, index)
        for name, index in sorted(before_by_name.items(), key=lambda item: item[0])
        if changed(name, index, after_by_name)
    ]
    creates: list[SnakeOperation] = [
        CreateIndex(after, index)
        for name, index in sorted(after_by_name.items(), key=lambda item: item[0])
        if changed(name, index, before_by_name)
    ]
    return drops, creates


def _diff_foreign_keys(
    before_by_name: dict[tuple[str, str], SnakeTableInfo],
    after: list[SnakeTableInfo],
    resolve_target: ResolveTarget,
    resolve_qualified: ResolveTarget | None = None,
) -> list[AddForeignKey | DropForeignKey]:
    """Compares each current table's relations (FKs) against the previous state.

    The return type NAMES the two operations instead of widening to `SnakeOperation`, because
    `diff_schema` now reads `.table` off them to work out which tables changed only a constraint.
    Widened, that read needed a cast, and a cast is a promise the checker stops verifying.
    """
    operations: list[AddForeignKey | DropForeignKey] = []
    for table in sorted(after, key=lambda t: t.name):
        before_table = before_by_name.get((table.schema, table.name))
        # Only to-one relations produce constraints: a to-many is the inverse (its FK lives on the
        # child) and one to/from a view is pure navigation. They are filtered out so no incorrect
        # ALTER TABLE is emitted.
        before_rels = {
            rel.name: rel
            for rel in (before_table.relationships if before_table else ())
            if rel.kind is SnakeRelationshipKind.TO_ONE
        }
        after_rels = {
            rel.name: rel
            for rel in table.relationships
            if rel.kind is SnakeRelationshipKind.TO_ONE
        }
        # Removals first, and the FKs that CHANGED too: in SQL a constraint is not altered in
        # place, it is dropped and recreated. The whole `foreign_key` is compared (not just the
        # name) so a change of `on_delete` or of columns does not slip through.
        for name in sorted(before_rels):
            if (
                name in after_rels
                and before_rels[name].foreign_key == after_rels[name].foreign_key
            ):
                continue
            target = _previous_target(before_rels[name], before_by_name, resolve_target)
            if target is not None:
                operations.append(DropForeignKey(table, before_rels[name], target))
        for name in sorted(after_rels):
            if (
                name in before_rels
                and before_rels[name].foreign_key == after_rels[name].foreign_key
            ):
                continue
            # The DESIRED side uses the target already resolved and qualified by the linker:
            # looking it up by class name would point at another model of the same name. The
            # PREVIOUS side does go by name (it is rebuilt from a migration, where the name is all
            # the information there is).
            target = _desired_target(
                after_rels[name], resolve_target, resolve_qualified
            )
            if target is not None:
                operations.append(AddForeignKey(table, after_rels[name], target))
    return operations


def _previous_target(
    relationship: SnakeRelationshipInfo,
    before_by_name: dict[tuple[str, str], SnakeTableInfo],
    resolve_target: ResolveTarget,
) -> SnakeTableInfo | None:
    """Target table of a relation being DROPPED, falling back to the PREVIOUS state.

    The registry is asked first, because it is the live truth. But a relation is dropped precisely
    when it leaves the code, and the commonest way for that to happen is that the target MODEL was
    deleted too. A deleted model is not in the registry, and answering `None` there makes the
    `DropForeignKey` VANISH in silence, leaving a plan with a bare `DropColumn` that MySQL (error
    1553) and SQLite both refuse.

    So it falls back to the previous state, which the migration history replays: it holds the target
    table with its real schema and its real columns — exactly what the reverse (`AddForeignKey`)
    needs to put the constraint back. It is the recorded table or nothing.

    The one case it cannot answer is a history so old that it recorded no `target_table` — the field
    is derived, and migrations written before it existed do not carry it. There the previous state
    holds the table and nothing says WHICH one it is, so this returns `None`.
    """
    target = resolve_target(relationship.foreign_key.target)
    if target is not None:
        return target
    if not relationship.target_table:
        return None
    schema, _, name = relationship.target_table.rpartition(".")
    return before_by_name.get((schema, name))


def _desired_target(
    relationship: SnakeRelationshipInfo,
    resolve_target: ResolveTarget,
    resolve_qualified: ResolveTarget | None,
) -> SnakeTableInfo | None:
    """Target table of a DESIRED relation, without going through the ambiguous name index."""
    if resolve_qualified is not None and relationship.target_table:
        resolved = resolve_qualified(relationship.target_table)
        if resolved is not None:
            return resolved
    return resolve_target(relationship.foreign_key.target)
