"""DDL generation from the metadata: SnakeTableInfo -> CREATE TABLE.

Each column gets its SQL type from the dialect (`map_type`): engine-specific DDL without
the metadata knowing any SQL. DDL is NOT parameterized (it describes the schema, not
user values).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from snakeorm.dialects import SnakeDialect
from snakeorm.dialects.capabilities import AlterColumnStyle, Cap, CommentStyle, Nope
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.core.exceptions import SnakeMigrationError, SnakeUnsupportedFeature
from snakeorm.metadata.type_params import SnakeStrParams
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeFkAction,
    SnakeIndexInfo,
    SnakeIndexMethod,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeRoutineInfo,
    SnakeTableInfo,
    SnakeTriggerInfo,
)
from snakeorm.sql.condition import emit_condition_ddl, inline_params
from snakeorm.sql.refs import qualified

if TYPE_CHECKING:
    from snakeorm.query import SnakeCompound, SnakeQuery

_CANONICAL_DIALECT: SnakeDialect = PostgresDialect()
"""The dialect a view FINGERPRINT is computed with. Nothing it emits is EVER executed.

It is Postgres because that is the reference engine of the project, and the choice does
not matter as long as it is FIXED: the only thing that counts about a fingerprint is
that it be the same on every machine. If it depended on the local engine, two devs with
different databases would generate different migrations out of the same model.
"""


def foreign_key_name(table: SnakeTableInfo, relationship: SnakeRelationshipInfo) -> str:
    """Deterministic name for the FK constraint (the same one in ADD and DROP).

    PUBLIC, which it did not need to be until `realize` had to NAME the constraint that stops a
    column from being dropped. It is DERIVED from the metadata and never read back out of the
    server's catalogue, so the plan can name it without a connection — the same property that lets
    `emit_drop_foreign_key` find again what `emit_add_foreign_key` wrote.
    """
    return f"fk_{table.name}_{relationship.name}"


def _uq_name(table: SnakeTableInfo, *column_names: str) -> str:
    """Deterministic name for a UNIQUE constraint (the SAME when adding and dropping).

    One single function for the two ways of asking for uniqueness
    (`snake_column(unique=True)` and `SnakeIndex(..., unique=True)`): they produce the
    SAME database object, so adding and dropping have to agree.
    """
    return f"uq_{table.name}_{'_'.join(column_names)}"


def _check_constraint_def(
    table: SnakeTableInfo, check: SnakeCheckInfo, dialect: SnakeDialect
) -> str:
    """`CONSTRAINT "ck_..." CHECK (...)` clause, emitted WITHOUT placeholders."""
    constraint = dialect.quote_ident(check.resolved_name(table.name))
    return f"CONSTRAINT {constraint} CHECK ({emit_condition_ddl(check.condition, dialect)})"


def emit_add_check(
    table: SnakeTableInfo, check: SnakeCheckInfo, dialect: SnakeDialect
) -> str:
    """Emits `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...)` for an existing table."""
    table_ref = qualified(table.schema, table.name, dialect)
    return f"ALTER TABLE {table_ref} ADD {_check_constraint_def(table, check, dialect)}"


def emit_drop_check(
    table: SnakeTableInfo, check: SnakeCheckInfo, dialect: SnakeDialect
) -> str:
    """The reverse: `ALTER TABLE ... DROP CONSTRAINT ...`, by the SAME resolved name."""
    table_ref = qualified(table.schema, table.name, dialect)
    constraint = dialect.quote_ident(check.resolved_name(table.name))
    return f"ALTER TABLE {table_ref} DROP CONSTRAINT {constraint}"


def _unique_constraint_def(
    table: SnakeTableInfo,
    columns: tuple[str, ...],
    dialect: SnakeDialect,
    name: str | None = None,
) -> str:
    """`CONSTRAINT "uq_..." UNIQUE (...)` clause, ALWAYS with an explicit name."""
    constraint = dialect.quote_ident(name or _uq_name(table, *columns))
    quoted = ", ".join(dialect.quote_ident(column) for column in columns)
    return f"CONSTRAINT {constraint} UNIQUE ({quoted})"


def inlined_foreign_keys(
    table: SnakeTableInfo, dialect: SnakeDialect
) -> tuple[SnakeRelationshipInfo, ...]:
    """The FKs this engine forces you to declare INSIDE the `CREATE TABLE`.

    With `supports_add_constraint` (Postgres) none of them: they go at the end. Without
    it (SQLite) the `CREATE TABLE` is the only window (`ADD CONSTRAINT` is a syntax
    error). A resolved `target_table` is required (the name of the table, not of the
    model); unresolved it is not inlined, and `realize` catches that. It exists as a
    function of its own (not an `if` inside the emitter) so that `realize` knows exactly
    which ones were inlined and can drop their redundant `AddForeignKey` without falling
    out of sync.
    """
    if dialect.supports_add_constraint:
        return ()
    return tuple(
        relationship
        for relationship in table.relationships
        if relationship.kind is SnakeRelationshipKind.TO_ONE
        and relationship.target_table
    )


def _inline_foreign_key_def(
    table: SnakeTableInfo, relationship: SnakeRelationshipInfo, dialect: SnakeDialect
) -> str:
    """`CONSTRAINT "fk_..." FOREIGN KEY (...) REFERENCES ...` clause for `CREATE TABLE`.

    Same name and same actions as the `ALTER` version: the key is the same, only the way
    it gets in changes.
    """
    quote = dialect.quote_ident
    fk = relationship.foreign_key
    schema, _, name = relationship.target_table.rpartition(".")
    local = ", ".join(quote(local_col) for local_col, _ in fk.pairs)
    remote = ", ".join(quote(remote_col) for _, remote_col in fk.pairs)
    sql = (
        f"CONSTRAINT {quote(foreign_key_name(table, relationship))} FOREIGN KEY ({local}) "
        f"REFERENCES {qualified(schema, name, dialect)} ({remote})"
    )
    if fk.on_delete is not SnakeFkAction.NO_ACTION:
        sql = f"{sql} ON DELETE {fk.on_delete.value}"
    if fk.on_update is not SnakeFkAction.NO_ACTION:
        sql = f"{sql} ON UPDATE {fk.on_update.value}"
    return sql


def _guard_text_primary_key(table: SnakeTableInfo, dialect: SnakeDialect) -> None:
    """Refuse a key column whose type has no length, on an engine that needs one.

    MySQL and MariaDB answer error 1170 to a `TEXT` column in a primary key and the whole
    `CREATE TABLE` dies. The ORM does NOT pick a length to make it work: inventing a `VARCHAR(255)`
    nobody asked for would truncate data the day a value outgrew it, and it would do so silently,
    which is worse than the refusal.

    It raises rather than warns because the outcome it prevents is not a degraded table but no table
    at all. The capability answers WHETHER the engine minds; this names WHICH column, which is the
    half a catalogue entry cannot carry.
    """
    support = dialect.capabilities.support_for(Cap.TEXT_IN_PRIMARY_KEY)
    if not isinstance(support, Nope):
        return
    for column in table.primary_key.columns:
        if column.python_type is not str:
            continue
        # Narrowed to the string params on purpose: `type_params` is a union and only that member
        # carries a length, so asking any other for one would be asking the wrong question.
        params = column.type_params
        if isinstance(params, SnakeStrParams) and params.max_length is not None:
            continue
        raise SnakeUnsupportedFeature(
            f"{type(dialect).__name__} cannot use '{column.name}' in the primary key of "
            f"'{table.name}': {support.reason}. Declare it with `max_length=` — the ORM will not "
            f"choose a length for you, because the one it made up would be the one that truncates."
        )


def emit_create_table(
    table: SnakeTableInfo, dialect: SnakeDialect, *, as_name: str | None = None
) -> str:
    """Emits the `CREATE TABLE` of a compiled table.

    Unique constraints are emitted with A NAME OF THEIR OWN (not a bare inline
    `UNIQUE`): the name Postgres would make up would not be found afterwards by the
    `DROP CONSTRAINT`. FKs only come in here on engines that cannot add them later (see
    `inlined_foreign_keys`).

    `as_name` creates it under ANOTHER name while every constraint keeps the one derived
    from `table.name`. It exists for the SQLite rebuild, which has to build the new table
    beside the old one and rename it into place: SQLite stores a constraint's name inside
    the table's own DDL, so a name taken from the temporary one would survive the rename
    and stay in the schema for ever, findable by nothing the metadata can spell.
    """
    _guard_text_primary_key(table, dialect)
    definitions = [_column_def(column, dialect) for column in table.columns]
    pk_columns = ", ".join(
        dialect.quote_ident(column.name) for column in table.primary_key.columns
    )
    definitions.append(f"PRIMARY KEY ({pk_columns})")
    definitions.extend(
        _unique_constraint_def(table, (column.name,), dialect)
        for column in table.columns
        if column.unique
    )
    definitions.extend(
        _check_constraint_def(table, check, dialect) for check in table.checks
    )
    definitions.extend(
        _inline_foreign_key_def(table, relationship, dialect)
        for relationship in inlined_foreign_keys(table, dialect)
    )

    table_ref = qualified(table.schema, as_name or table.name, dialect)
    create = f"CREATE TABLE {table_ref} ({', '.join(definitions)})"
    if _comments_are_inline(dialect) and table.db_comment is not None:
        # On this engine the table comment is a CLAUSE, so it travels with the CREATE and there is
        # no second statement. `emit_comments` returns nothing here for exactly that reason.
        create += f" COMMENT = {dialect.literal(table.db_comment)}"
    return create


def _comments_are_inline(dialect: SnakeDialect) -> bool:
    """Whether this engine spells a comment as a CLAUSE rather than a statement of its own."""
    return dialect.syntax.comment_style is CommentStyle.INLINE


def _inline_comment_literal(comment: str | None, dialect: SnakeDialect) -> str:
    """The text of an inline `COMMENT` clause, with REMOVAL spelled as the empty string.

    Not `dialect.literal(comment)`, and the difference only shows up on the rollback path.
    `literal(None)` returns `NULL` on every dialect —which is right for `COMMENT ON ... IS NULL`—
    and measured against MariaDB 11.8.8, `ALTER TABLE t COMMENT = NULL` is `ERROR 1064`. This engine
    clears a comment by assigning the empty string, which is also how it stores "no comment": its
    `information_schema` returns `''`, never NULL.
    """
    return dialect.literal(comment if comment is not None else "")


def emit_table_comment(table: SnakeTableInfo, dialect: SnakeDialect) -> str:
    """The statement that sets (or clears) a TABLE's comment, in the grammar of the engine.

    Two spellings for one intention, which is what a dialect is for. Postgres has a statement of its
    own (`COMMENT ON TABLE ... IS ...`, and `IS NULL` removes it); MySQL has a CLAUSE
    (`ALTER TABLE ... COMMENT = ...`, and the empty string removes it). The text goes through
    `dialect.literal` in both, like DEFAULT and CHECK, so a quote inside it breaks nothing.

    `CommentStyle.UNSUPPORTED` (SQLite) falls into the first branch and never runs: `Cap.COMMENTS`
    is `Nope` there, so `realize` stops the operation in the PLAN — the same arrangement
    `_alter_column_by_alter` already relies on.
    """
    table_ref = qualified(table.schema, table.name, dialect)
    if _comments_are_inline(dialect):
        return (
            f"ALTER TABLE {table_ref} "
            f"COMMENT = {_inline_comment_literal(table.db_comment, dialect)}"
        )
    return f"COMMENT ON TABLE {table_ref} IS {dialect.literal(table.db_comment)}"


def emit_column_comment(
    table: SnakeTableInfo, column: SnakeColumnInfo, dialect: SnakeDialect
) -> str:
    """The statement that sets (or clears) a COLUMN's comment. This is the degraded half.

    Postgres writes `COMMENT ON COLUMN ... IS '...'`, which touches one catalogue row and nothing
    else. MySQL has NO statement that changes a column's comment on its own — measured,
    `ALTER COLUMN c COMMENT` is a 1064 and `MODIFY COLUMN c COMMENT` is error 4161 — so the only
    spelling is a `MODIFY COLUMN` carrying the WHOLE definition.

    That is why `_column_def` is reused rather than a comment clause pasted on: a `MODIFY` deletes
    everything it does not respell, and measured on MariaDB the naive shape turned a
    `NOT NULL DEFAULT 7` into `DEFAULT NULL` and dropped an `AUTO_INCREMENT` in silence. Respelling
    from the metadata is what keeps everything the model knows. What the model does NOT describe is
    lost, and `Cap.COMMENTS` says so as `Degraded` rather than `Full`.
    """
    if _comments_are_inline(dialect):
        table_ref = qualified(table.schema, table.name, dialect)
        return f"ALTER TABLE {table_ref} MODIFY COLUMN {_column_def(column, dialect)}"
    quote = dialect.quote_ident
    column_ref = f"{qualified(table.schema, table.name, dialect)}.{quote(column.name)}"
    return f"COMMENT ON COLUMN {column_ref} IS {dialect.literal(column.db_comment)}"


def emit_comments(table: SnakeTableInfo, dialect: SnakeDialect) -> list[str]:
    """The EXTRA statements a freshly created table needs for its comments. Often none.

    Empty for two different reasons, and keeping them apart matters:

    - `CommentStyle.INLINE` (MySQL): the comments already travelled inside the `CREATE TABLE`,
      table and columns alike. Emitting them again would write each one twice.
    - `Cap.COMMENTS` absent (SQLite): the engine stores none, and it gets TRANSLATED into nothing
      instead of complaining — a comment is documentation, not integrity, and losing it does not
      corrupt data. Project rule: translate when there is an equivalent, complain when there is none.
    """
    if not dialect.supports_comments or _comments_are_inline(dialect):
        return []
    statements: list[str] = []
    if table.db_comment is not None:
        statements.append(emit_table_comment(table, dialect))
    statements.extend(
        emit_column_comment(table, column, dialect)
        for column in table.columns
        if column.db_comment is not None
    )
    return statements


def emit_create_schema(schema: str, dialect: SnakeDialect) -> str:
    """Emits `CREATE SCHEMA IF NOT EXISTS "name"`.

    `IF NOT EXISTS` because the DBA may have created the schema beforehand: failing then
    adds nothing, the desired state already holds.
    """
    return f"CREATE SCHEMA IF NOT EXISTS {dialect.quote_ident(schema)}"


def emit_drop_schema(schema: str, dialect: SnakeDialect) -> str:
    """Emits `DROP SCHEMA "name"` (the reverse, deliberately WITHOUT CASCADE).

    No `CASCADE`: if anything is left inside, let it fail. Wiping out what it did not
    create is worse than refusing.
    """
    return f"DROP SCHEMA {dialect.quote_ident(schema)}"


def emit_drop_table(table: SnakeTableInfo, dialect: SnakeDialect) -> str:
    """Emits the `DROP TABLE` of a table (the reverse of CREATE TABLE)."""
    table_ref = qualified(table.schema, table.name, dialect)
    return f"DROP TABLE {table_ref}"


def _emitted_as_constraint(index: SnakeIndexInfo, dialect: SnakeDialect) -> bool:
    """Is this index written as a CONSTRAINT on this engine, or as a unique index?

    `is_constraint` is the declared INTENT (engine-agnostic); the FORM is decided by the
    engine. Without `ADD CONSTRAINT` (SQLite) it is translated into `CREATE UNIQUE
    INDEX`, which gives the same guarantee. The NAME (`uq_*`) does not change: the
    metadata fixes it and adding and dropping have to agree.
    """
    return index.is_constraint and dialect.supports_add_constraint


def emit_create_index(
    table: SnakeTableInfo, index: SnakeIndexInfo, dialect: SnakeDialect
) -> str:
    """The DDL that adds a declared index: a CONSTRAINT with `unique`, an INDEX if not.

    Uniqueness goes as a constraint (not as a unique index) because it STATES a rule of
    the domain —the one `ON CONFLICT` and the engine errors refer to—; the index is only
    the how. On an engine without `ADD CONSTRAINT` it falls back to the `CREATE UNIQUE
    INDEX`; see `_emitted_as_constraint`.
    """
    name = dialect.quote_ident(index.resolved_name(table.name))
    columns = ", ".join(dialect.quote_ident(column) for column in index.columns)
    table_ref = qualified(table.schema, table.name, dialect)
    if _emitted_as_constraint(index, dialect):
        return (
            f"ALTER TABLE {table_ref} ADD "
            f"{_unique_constraint_def(table, index.columns, dialect, index.name)}"
        )
    # A PARTIAL unique does not fit in a constraint (Postgres does not accept `UNIQUE
    # ... WHERE`), so here a `CREATE UNIQUE INDEX` does come out. It is the documented
    # exception.
    unique = "UNIQUE " if index.unique else ""
    # BTREE is the engine default: the USING is omitted instead of writing the obvious.
    using = (
        f" USING {dialect.index_method(index.method)}"
        if index.method is not None and index.method is not SnakeIndexMethod.BTREE
        else ""
    )
    # The `WHERE` is only written where the engine HAS partial indexes. MySQL/MariaDB do not: the
    # clause is not in their `CREATE INDEX` grammar, so writing it earned an ERROR 1064 from the
    # server — the ORM emitting SQL that gets rejected, which is neither stopping nor degrading.
    #
    # Dropping it here degrades a SEARCH index into one over the whole table: same rows found, same
    # data stored, more space. A partial UNIQUE cannot be degraded this way —widening it forbids
    # rows the domain allows— and `realize()` stops it before this ever runs. The reason reaches the
    # user through `Cap.PARTIAL_INDEXES`, announced once when the session opens.
    where = (
        f" WHERE {emit_condition_ddl(index.where, dialect)}"
        if index.where is not None and dialect.capabilities.can(Cap.PARTIAL_INDEXES)
        else ""
    )
    return f"CREATE {unique}INDEX {name} ON {table_ref}{using} ({columns}){where}"


def emit_drop_index(
    table: SnakeTableInfo, index: SnakeIndexInfo, dialect: SnakeDialect
) -> str:
    """The drop DDL: `DROP CONSTRAINT` for uniqueness, `DROP INDEX` for an index.

    An index is qualified with the SCHEMA (it is an object of the schema); a constraint
    is dropped through ITS TABLE. Both by the resolved name, the same one the add used.
    """
    name = dialect.quote_ident(index.resolved_name(table.name))
    if _emitted_as_constraint(index, dialect):
        table_ref = qualified(table.schema, table.name, dialect)
        return f"ALTER TABLE {table_ref} DROP CONSTRAINT {name}"
    # Two SEPARATE decisions, and they were conflated into one: the condition for naming
    # the table was `supports_schemas`, which has nothing to do with it. MySQL, which
    # has no schemas, fell into the short branch because of that and was also left
    # without the `ON table` it does need — and since the caller here is
    # `CreateIndex.down_sql`, the rollback of every migration with an index died.
    if dialect.syntax.indexes_are_table_scoped:
        return f"DROP INDEX {name} ON {qualified(table.schema, table.name, dialect)}"
    if not dialect.supports_schemas:
        return f"DROP INDEX {name}"
    return f"DROP INDEX {dialect.quote_ident(table.schema)}.{name}"


def emit_add_column(
    table: SnakeTableInfo, column: SnakeColumnInfo, dialect: SnakeDialect
) -> str:
    """Emits `ALTER TABLE ... ADD COLUMN <def>`.

    Warning: adding a NOT NULL column without a DEFAULT to a table that has rows fails
    on Postgres; declare a default or make it nullable.
    """
    table_ref = qualified(table.schema, table.name, dialect)
    return f"ALTER TABLE {table_ref} ADD COLUMN {_column_def(column, dialect)}"


def emit_drop_column(
    table: SnakeTableInfo, column_name: str, dialect: SnakeDialect
) -> str:
    """Emits `ALTER TABLE ... DROP COLUMN "col"`."""
    table_ref = qualified(table.schema, table.name, dialect)
    return f"ALTER TABLE {table_ref} DROP COLUMN {dialect.quote_ident(column_name)}"


def emit_rename_column(
    table: SnakeTableInfo, old_name: str, new_name: str, dialect: SnakeDialect
) -> str:
    """Emits `ALTER TABLE ... RENAME COLUMN old TO new`.

    Renaming KEEPS the data; the drop + add the diff would produce erases it. It is
    written by hand because the diff does not guess a rename.
    """
    table_ref = qualified(table.schema, table.name, dialect)
    return (
        f"ALTER TABLE {table_ref} RENAME COLUMN "
        f"{dialect.quote_ident(old_name)} TO {dialect.quote_ident(new_name)}"
    )


def emit_rename_table(
    table: SnakeTableInfo, new_name: str, dialect: SnakeDialect
) -> str:
    """Emits `ALTER TABLE <table> RENAME TO "new"`, the same grammar on the three engines.

    THE OLD NAME IS QUALIFIED AND THE NEW ONE IS NOT, and that is measured rather than chosen:
    PostgreSQL answers a syntax error to `RENAME TO "public"."new"`. It reads natural and it does
    not parse, because a rename cannot move a table between schemas — that is `SET SCHEMA`, a
    different statement. MariaDB and SQLite take the bare form too, so there is nothing to
    translate: one string, three quotings, which `qualified` and `quote_ident` already handle.
    """
    table_ref = qualified(table.schema, table.name, dialect)
    return f"ALTER TABLE {table_ref} RENAME TO {dialect.quote_ident(new_name)}"


REBUILD_SCRATCH_PREFIX = "__snakeorm_new_"
"""Prefix of the table a rebuild builds beside the original before renaming it into place.

Deterministic and derived from the table's own name, like every other identifier the migrations
emit: nothing here is ever read back out of the server, so the `DROP` and the `RENAME` that follow
can name it without a connection. The prefix is long and ugly on purpose — it has to be a name no
model would ever declare, and it lives in the schema for exactly three statements.
"""


def rebuild_scratch_name(table: SnakeTableInfo) -> str:
    """The temporary name the rebuild of this table uses."""
    return f"{REBUILD_SCRATCH_PREFIX}{table.name}"


def _to_one_keys(table: SnakeTableInfo) -> dict[str, SnakeRelationshipInfo]:
    """The table's to-one relations by CONSTRAINT NAME, which is their identity in the database.

    Only to-one: a to-many is the inverse relation and its key lives on the other table, the same
    filter `_diff_foreign_keys` and `drop_order` already apply.
    """
    return {
        foreign_key_name(table, relationship): relationship
        for relationship in table.relationships
        if relationship.kind is SnakeRelationshipKind.TO_ONE
    }


def _check_fingerprints(table: SnakeTableInfo, dialect: SnakeDialect) -> dict[str, str]:
    """The table's CHECKs by resolved name, valued by the SQL they emit.

    Compared by the emitted condition and not by the object: the AST nodes use `eq=False`, so two
    identical conditions are never `==` and every rebuild would look like it changed everything.
    """
    return {
        check.resolved_name(table.name): emit_condition_ddl(check.condition, dialect)
        for check in table.checks
    }


def _add_foreign_key_clause(
    table: SnakeTableInfo, relationship: SnakeRelationshipInfo, dialect: SnakeDialect
) -> str:
    """`ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ...` taken from the relation's OWN target.

    It reuses `_inline_foreign_key_def`, so the key an engine writes inside its `CREATE TABLE` and
    the one another engine adds afterwards are the SAME text with a different preamble — one name,
    one set of referential actions, and no second place where they could drift.

    It reads `relationship.target_table` instead of taking a resolved `SnakeTableInfo` the way
    `emit_add_foreign_key` does, because a rebuild is described by two snapshots of ONE table and
    there is no second table in the operation to hand over. The field is the linker's own resolved
    spelling, which is what the inline form already trusts.
    """
    table_ref = qualified(table.schema, table.name, dialect)
    return f"ALTER TABLE {table_ref} ADD {_inline_foreign_key_def(table, relationship, dialect)}"


def _minimal_constraint_alters(
    before: SnakeTableInfo, after: SnakeTableInfo, dialect: SnakeDialect
) -> list[str]:
    """The least an engine with `ALTER TABLE ... ADD CONSTRAINT` has to run: drops, then adds.

    Drops first and adds after, which is the order `_diff_checks` and `_diff_foreign_keys` already
    put them in and for the same reason: a constraint is not altered in place, so one that changed
    under the same name has to leave before its replacement arrives.
    """
    before_checks = _check_fingerprints(before, dialect)
    after_checks = _check_fingerprints(after, dialect)
    before_keys = _to_one_keys(before)
    after_keys = _to_one_keys(after)

    statements: list[str] = [
        emit_drop_check(before, check, dialect)
        for check in before.checks
        if after_checks.get(check.resolved_name(before.name))
        != before_checks[check.resolved_name(before.name)]
    ]
    statements.extend(
        emit_drop_foreign_key(before, relationship, dialect)
        for name, relationship in before_keys.items()
        if name not in after_keys
        or after_keys[name].foreign_key != relationship.foreign_key
        or after_keys[name].target_table != relationship.target_table
    )
    statements.extend(
        _add_foreign_key_clause(after, relationship, dialect)
        for name, relationship in after_keys.items()
        if name not in before_keys
        or before_keys[name].foreign_key != relationship.foreign_key
        or before_keys[name].target_table != relationship.target_table
    )
    statements.extend(
        emit_add_check(after, check, dialect)
        for check in after.checks
        if before_checks.get(check.resolved_name(after.name))
        != after_checks[check.resolved_name(after.name)]
    )
    return statements


def _remake_table(
    before: SnakeTableInfo,
    after: SnakeTableInfo,
    dialect: SnakeDialect,
    triggers: Sequence[SnakeTriggerInfo] = (),
) -> list[str]:
    """The whole rebuild, for an engine whose only window on a constraint is the `CREATE TABLE`.

    THE ORDER IS THE ONE THAT WORKS. The new table is built beside the old one and renamed into
    place last; renaming the OLD one out of the way first needs `PRAGMA foreign_keys = OFF`, because
    a rename rewrites the `REFERENCES` clauses of every other table while the keys are armed — and
    that pragma is documented as a no-op inside a transaction, which is where a migration always is.

    The indexes are recreated at the END, after the `DROP TABLE` has taken the old ones with it:
    creating them earlier would clash with names that are still occupied. They come from `after`, so
    an index the model does NOT declare does not come back — one created by hand in the database is
    gone after a rebuild.

    THE TRIGGERS GO LAST FOR THE SAME REASON, and they arrive by a different road: a `SnakeTableInfo`
    has no `triggers` field, so `after` cannot carry them and the operation passes them in. They also
    have to come after the RENAME, since the statement that creates one names the table it hangs off
    and that name only becomes the real one at the end.

    NO VIEW IS BRACKETED AROUND IT (see `emit_rebuild_table`). The `RENAME` at the end REPARSES THE
    ENTIRE SCHEMA on this engine, and at that instant the old table is already dropped and the new
    one still wears its scratch name — so a view whose SELECT names the table cannot be parsed and
    the RENAME fails with `error in view <v>: no such table: main.<t>`, measured on SQLite 3.50; it
    is that statement that fails, not the `DROP TABLE`. `frameworks/shared/migrations/inventory/
    0004_on_hand_and_available_view.py` is the worked example, with the `DropView` before and the
    `CreateView` after written by hand.
    """
    scratch = rebuild_scratch_name(after)
    columns = ", ".join(dialect.quote_ident(column.name) for column in after.columns)
    statements: list[str] = []
    if dialect.syntax.defer_constraints_statement is not None:
        statements.append(dialect.syntax.defer_constraints_statement)
    statements.extend(
        (
            emit_create_table(after, dialect, as_name=scratch),
            f"INSERT INTO {qualified(after.schema, scratch, dialect)} ({columns}) "
            f"SELECT {columns} FROM {qualified(before.schema, before.name, dialect)}",
            emit_drop_table(before, dialect),
            emit_rename_table(replace(after, name=scratch), after.name, dialect),
        )
    )
    statements.extend(
        emit_create_index(after, index, dialect) for index in after.indexes
    )
    for trigger in triggers:
        statements.extend(emit_create_trigger(trigger, dialect))
    return statements


def emit_rebuild_table(
    before: SnakeTableInfo,
    after: SnakeTableInfo,
    dialect: SnakeDialect,
    triggers: Sequence[SnakeTriggerInfo] = (),
) -> list[str]:
    """Takes a table from the `before` shape to the `after` one, in the way this engine can.

    Two spellings of ONE operation: an engine that can change a constraint in place gets the minimal
    `ALTER`s, and an engine that cannot gets the table remade around it.

    The two snapshots differ only in constraints; `RebuildTable` refuses to be built otherwise, so
    nothing here has to guess whether a column change was meant to travel.

    The `triggers` are the ones hanging off this table, and only the engine that REMAKES it has
    anything to do with them: an engine that alters the constraint in place never drops the table,
    so nothing took them away and recreating them would collide with names still in use.

    Views are NOT part of this call in either spelling. The engine that remakes the table is the one
    a standing view can break, and which views read the table is not something the metadata says —
    so the person writes the `DropView`/`CreateView` around the rebuild, and the ORM translates the
    engine's complaint when they did not.
    """
    if dialect.supports_add_constraint:
        return _minimal_constraint_alters(before, after, dialect)
    return _remake_table(before, after, dialect, triggers)


def emit_alter_column(
    table: SnakeTableInfo,
    old: SnakeColumnInfo,
    new: SnakeColumnInfo,
    dialect: SnakeDialect,
) -> list[str]:
    """The statements to go from `old` to `new`, in the GRAMMAR of the engine.

    Scope: type, nullable, unique and default. The reverse (down) is obtained by
    swapping old/new.

    The form is decided by `dialect.syntax.alter_column_style` and not by this emitter,
    which is exactly what was wrong: it wrote the Postgres one for everybody. MySQL
    declares that it knows how to alter columns —and it does—, so the plan let the
    operation through and the failure came out as a syntax error from the engine halfway
    through the migration; with no transactional DDL, that is, with no rollback.
    """
    if dialect.syntax.alter_column_style is AlterColumnStyle.MYSQL_MODIFY:
        statements = _alter_column_by_modify(table, old, new, dialect)
    else:
        # POSTGRES_TYPE_USING, and UNSUPPORTED too: on an engine that does not know how
        # to alter columns this never gets to run —`realize()` stops the operation in
        # the PLAN, with a readable reason—, so whatever form is emitted there does not
        # matter as long as nobody runs it.
        statements = _alter_column_by_alter(table, old, new, dialect)
    if (
        new.db_comment != old.db_comment
        and dialect.supports_comments
        and not _comments_are_inline(dialect)
    ):
        # The capability was already read here —without it, altering a commented column slipped a
        # `COMMENT ON` into engines that do not understand it— and now the STYLE is read too. On an
        # inline engine the comment is part of the definition, so `_alter_column_by_modify` has
        # already carried it in its `MODIFY`; appending a second statement would rewrite the column
        # twice to say the same thing.
        statements.append(emit_column_comment(table, new, dialect))
    return statements


def _alter_column_by_alter(
    table: SnakeTableInfo,
    old: SnakeColumnInfo,
    new: SnakeColumnInfo,
    dialect: SnakeDialect,
) -> list[str]:
    """Postgres form: one statement per change, and a `USING` to cast the type.

    The autoincrement is NOT one more property here, and that is the whole difference from the
    MySQL form: `BIGSERIAL` is not a type this engine has, it is a `CREATE TABLE` shorthand. So the
    toggle is expanded into what the shorthand means (see `_autoincrement_change`) and the type
    statement is written with the STORABLE type, never with the shorthand.
    """
    table_ref = qualified(table.schema, table.name, dialect)
    column = dialect.quote_ident(new.name)
    statements: list[str] = []
    new_type = _storable_type(new, dialect)
    if new_type != _storable_type(old, dialect):
        statements.append(
            f"ALTER TABLE {table_ref} ALTER COLUMN {column} "
            f"TYPE {new_type} USING {column}::{new_type}"
        )
    if new.nullable != old.nullable:
        action = "DROP NOT NULL" if new.nullable else "SET NOT NULL"
        statements.append(f"ALTER TABLE {table_ref} ALTER COLUMN {column} {action}")
    statements.extend(_unique_change(table, old, new, dialect))
    if old.autoincrement != new.autoincrement:
        # The sequence OWNS the DEFAULT at both ends of the toggle, so the ordinary default branch
        # would only fight it: turning it on the default IS `nextval(...)`, and turning it off the
        # `DROP DEFAULT` is already part of dismantling the sequence.
        return statements + _autoincrement_change(table, new, dialect)
    if _default_changed(old, new):
        expression = _default_expr(new, dialect)
        if expression is not None:
            statements.append(
                f"ALTER TABLE {table_ref} ALTER COLUMN {column} SET DEFAULT {expression}"
            )
        else:
            statements.append(
                f"ALTER TABLE {table_ref} ALTER COLUMN {column} DROP DEFAULT"
            )
    return statements


def _storable_type(column: SnakeColumnInfo, dialect: SnakeDialect) -> str:
    """The column's type as an `ALTER ... TYPE` can spell it: the shorthand resolved away.

    `sql_type_of` answers what a `CREATE TABLE` writes, and on Postgres an autoincrementing column
    writes `BIGSERIAL` there. That word only exists in a `CREATE TABLE`: the server answers
    `type "bigserial" does not exist` to an `ALTER ... TYPE BIGSERIAL`, which is what this emitter
    used to produce. Asking for the type WITHOUT the autoincrement gives the type the column really
    has —`BIGINT`—, which is the one an `ALTER` can name.
    """
    return dialect.map_type(
        column.storage_type, autoincrement=False, params=column.type_params
    )


def _sequence_name(table: SnakeTableInfo, column: SnakeColumnInfo) -> str:
    """The name Postgres itself gives the sequence behind a `SERIAL`: `<table>_<column>_seq`.

    Derived and not stored, and it has to be exactly this one: a column born `BIGSERIAL` inside a
    `CREATE TABLE` already has a sequence under this name, so a later toggle finds it instead of
    leaving a second, orphaned one behind.
    """
    return f"{table.name}_{column.name}_seq"


def _autoincrement_change(
    table: SnakeTableInfo, new: SnakeColumnInfo, dialect: SnakeDialect
) -> list[str]:
    """What `SERIAL` MEANS, spelled out: a sequence, a `DEFAULT nextval(...)` and its owner.

    Turning it ON, four statements. `OWNED BY` is what makes the sequence die with the column, just
    as it does when the shorthand creates it. And the `setval` is not decoration: over a populated
    table a fresh sequence starts at 1 and the first insert collides with a key that is already
    there. `is_called = false` means the NEXT `nextval()` returns exactly that value, so an empty
    table (`MAX` is NULL, hence `COALESCE` 0) starts at 1, like a brand-new `BIGSERIAL`.

    Turning it OFF, two. This is the direction that used to be worse: it emitted
    `TYPE BIGINT USING "code"::BIGINT` on a column that was ALREADY `bigint`, so the server accepted
    it, changed nothing, and left the `DEFAULT nextval(...)` and the sequence in place. A green
    migration that did not migrate. Failing loudly is bad; succeeding and lying is worse.
    """
    table_ref = qualified(table.schema, table.name, dialect)
    column = dialect.quote_ident(new.name)
    sequence = qualified(table.schema, _sequence_name(table, new), dialect)
    if not new.autoincrement:
        return [
            f"ALTER TABLE {table_ref} ALTER COLUMN {column} DROP DEFAULT",
            f"DROP SEQUENCE {sequence}",
        ]
    return [
        f"CREATE SEQUENCE {sequence}",
        f"ALTER TABLE {table_ref} ALTER COLUMN {column} SET DEFAULT "
        f"nextval({dialect.literal(sequence)}::regclass)",
        f"ALTER SEQUENCE {sequence} OWNED BY {table_ref}.{column}",
        f"SELECT setval({dialect.literal(sequence)}, "
        f"COALESCE((SELECT MAX({column}) FROM {table_ref}), 0) + 1, false)",
    ]


def _alter_column_by_modify(
    table: SnakeTableInfo,
    old: SnakeColumnInfo,
    new: SnakeColumnInfo,
    dialect: SnakeDialect,
) -> list[str]:
    """MySQL form: `MODIFY COLUMN` with the WHOLE definition, in ONE statement.

    `MODIFY` does not change one property, it rewrites the definition completely. That
    is why type, nullability and default travel together: emitting one statement per
    change —as in Postgres— would have the second one trample what the first left
    behind, and a column that only changed type would lose its NOT NULL.

    Uniqueness does NOT come in here: in MySQL it is a constraint apart as well, with a
    name of its own.

    The COMMENT is in the trigger list for the same reason the others are: it lives inside the
    definition, so a comment-only edit still needs the whole `MODIFY`. Before it was listed, such an
    edit produced an EMPTY statement list on this engine — the diff saw the change, wrote it into
    the migration file, and applying the file did nothing at all.
    """
    table_ref = qualified(table.schema, table.name, dialect)
    statements: list[str] = []
    if (
        sql_type_of(new, dialect) != sql_type_of(old, dialect)
        or new.nullable != old.nullable
        or _default_changed(old, new)
        or new.db_comment != old.db_comment
    ):
        statements.append(
            f"ALTER TABLE {table_ref} MODIFY COLUMN {_column_def(new, dialect)}"
        )
    statements.extend(_unique_change(table, old, new, dialect))
    return statements


def _unique_change(
    table: SnakeTableInfo,
    old: SnakeColumnInfo,
    new: SnakeColumnInfo,
    dialect: SnakeDialect,
) -> list[str]:
    """Adding or dropping the uniqueness constraint, written alike on both engines."""
    if new.unique == old.unique:
        return []
    table_ref = qualified(table.schema, table.name, dialect)
    constraint = dialect.quote_ident(_uq_name(table, new.name))
    if new.unique:
        column = dialect.quote_ident(new.name)
        return [
            f"ALTER TABLE {table_ref} ADD CONSTRAINT {constraint} UNIQUE ({column})"
        ]
    return [f"ALTER TABLE {table_ref} DROP CONSTRAINT {constraint}"]


def emit_add_foreign_key(
    table: SnakeTableInfo,
    relationship: SnakeRelationshipInfo,
    target: SnakeTableInfo,
    dialect: SnakeDialect,
) -> str:
    """Emits `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY (...) REFERENCES ...`.

    FKs are added AT THE END (after every table has been created), so `target` is
    already resolved here and no topological order is needed. Emits ON DELETE/UPDATE
    when they are not NO ACTION.
    """
    quote = dialect.quote_ident
    fk = relationship.foreign_key
    local = ", ".join(quote(local_col) for local_col, _ in fk.pairs)
    remote = ", ".join(quote(remote_col) for _, remote_col in fk.pairs)
    source_ref = qualified(table.schema, table.name, dialect)
    target_ref = qualified(target.schema, target.name, dialect)
    sql = (
        f"ALTER TABLE {source_ref} ADD CONSTRAINT {quote(foreign_key_name(table, relationship))} "
        f"FOREIGN KEY ({local}) REFERENCES {target_ref} ({remote})"
    )
    if fk.on_delete is not SnakeFkAction.NO_ACTION:
        sql = f"{sql} ON DELETE {fk.on_delete.value}"
    if fk.on_update is not SnakeFkAction.NO_ACTION:
        sql = f"{sql} ON UPDATE {fk.on_update.value}"
    return sql


def emit_drop_foreign_key(
    table: SnakeTableInfo, relationship: SnakeRelationshipInfo, dialect: SnakeDialect
) -> str:
    """Emits `ALTER TABLE ... DROP CONSTRAINT ...` (the reverse of ADD)."""
    source_ref = qualified(table.schema, table.name, dialect)
    return f"ALTER TABLE {source_ref} DROP CONSTRAINT {dialect.quote_ident(foreign_key_name(table, relationship))}"


def _view_ref(view: SnakeTableInfo, dialect: SnakeDialect) -> str:
    """Qualified `"schema"."view"` reference of a view."""
    return qualified(view.schema, view.name, dialect)


def view_body(view: SnakeTableInfo, dialect: SnakeDialect) -> str:
    """The SELECT that defines the view, written in the TARGET dialect.

    With `query=` it is compiled here and not when the model is declared: quoting,
    schema qualification, literals and `LIMIT/OFFSET` change between engines, and
    compiling it in the decorator froze the body into the dialect of a single one.

    With `sql=` it is returned as is. The user wrote it in the dialect of their engine,
    so there is nothing to recompile and reinterpreting it would be worse.
    """
    if view.view_query is not None:
        # The cast names the WHOLE union the decorator accepts, not just the query. It said
        # `SnakeQuery` while a compound already flowed through it correctly, so the one place that
        # knows what a view body can be was describing half of it.
        query = cast(
            "SnakeQuery[object] | SnakeCompound[object]",
            view.view_query,
        )
        text, params = query.to_sql(dialect)
        # The `CREATE VIEW ... AS <select>` DDL does not accept placeholders: the
        # literals of the filter get inlined (the same piece the CHECKs use).
        return inline_params(text, params, dialect)
    return _raw_view_definition(view)


def view_fingerprint(view: SnakeTableInfo) -> str:
    """The fingerprint a view is COMPARED by between two states of the schema.

    It is computed with a CANONICAL dialect and is never executed. It has to be the same
    on the three engines because the snapshot and the diff come out of it: if it
    depended on the engine, the same model would generate a different migration
    depending on the machine `makemigrations` is run from, and two devs with different
    engines would trample each other's history.

    It is the separation that was missing. Before, one single string acted as
    fingerprint AND as DDL, so one of them could not be fixed without breaking the
    other.
    """
    return view_body(view, _CANONICAL_DIALECT)


def _raw_view_definition(view: SnakeTableInfo) -> str:
    """The definition (SELECT) of a view; fails clearly if the node lacks it."""
    if view.view_definition is None:
        raise SnakeMigrationError(
            f"View '{view.name}' has no definition (view_definition); its DDL cannot be emitted. "
            f"Was it compiled with @snake_view (sql=... or query=...)?"
        )
    return view.view_definition


def emit_create_view(view: SnakeTableInfo, dialect: SnakeDialect) -> str:
    """Emits `CREATE VIEW "schema"."view" AS <definition>` (raw SELECT, on purpose).

    A view emits NO FKs and NO constraints: navigating its relations is pure SQL
    generation, the database does not guarantee it. Views are created AFTER the tables
    (they depend on them).
    """
    return f"CREATE VIEW {_view_ref(view, dialect)} AS {view_body(view, dialect)}"


def emit_drop_view(view: SnakeTableInfo, dialect: SnakeDialect) -> str:
    """Emits `DROP VIEW "schema"."view"` (the reverse of CREATE VIEW)."""
    return f"DROP VIEW {_view_ref(view, dialect)}"


def topological_view_order(views: Sequence[SnakeTableInfo]) -> list[SnakeTableInfo]:
    """Orders the views so each one comes AFTER those it depends on (`depends_on`).

    Only dependencies WITHIN the given set count (a dependency on a view that already exists — not in
    the set — imposes no order here). A DFS with an "in progress" mark detects cycles and raises
    `SnakeMigrationError`. The walk starts in name order -> stable output.

    IT LIVES IN THE EMITTER AND NOT IN THE DIFF, and today it has ONE caller: `_diff_views`, which
    orders the `CreateView`/`DropView` operations. It had a second — `_remake_table` bracketed a
    rebuild with the standing views — and that second caller was removed on purpose, because the ORM
    cannot know which tables a view reads. Moving the function back into `diff.py` for that would be
    churn with a cost: `diff` already imports `view_fingerprint` from here, so the arrow between the
    two modules only goes one way, and this is the module that spells view DDL.
    """
    by_name = {view.name: view for view in views}
    ordered: list[SnakeTableInfo] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(view: SnakeTableInfo) -> None:
        if view.name in visited:
            return
        if view.name in visiting:
            raise SnakeMigrationError(
                f"Dependency cycle among views: '{view.name}' takes part in a `depends_on` "
                f"cycle. A view cannot depend (directly or indirectly) on itself."
            )
        visiting.add(view.name)
        for dependency in view.depends_on:
            target = by_name.get(dependency)
            if (
                target is not None
            ):  # dependencies outside the set already exist: they impose no order
                visit(target)
        visiting.discard(view.name)
        visited.add(view.name)
        ordered.append(view)

    for view in sorted(views, key=lambda item: item.name):
        visit(view)
    return ordered


def emit_replace_view(view: SnakeTableInfo, dialect: SnakeDialect) -> str:
    """Emits `CREATE OR REPLACE VIEW ... AS <definition>` (to change a view SELECT).

    It replaces the whole view: a view has no AddColumn/AlterColumn, it is redefined in
    one piece.
    """
    return f"CREATE OR REPLACE VIEW {_view_ref(view, dialect)} AS {view_body(view, dialect)}"


# -- ROUTINE DDL (stored functions/procedures) -----------------------------------------
#
# A routine is OPAQUE SQL: its `body` is the complete `CREATE OR REPLACE FUNCTION ...`,
# raw and NOT portable. The create/replace emitter returns the `body` as is; only the
# `DROP FUNCTION` of the reverse is built out of the name.


def emit_create_function(routine: SnakeRoutineInfo, dialect: SnakeDialect) -> str:
    """The DDL of a routine: its raw `body` (opaque, not portable, `CREATE OR REPLACE`).

    It serves CreateFunction and AlterFunction alike: with `CREATE OR REPLACE` both of
    them are idempotent.
    """
    return routine.body


def emit_drop_function(routine: SnakeRoutineInfo, dialect: SnakeDialect) -> str:
    """Builds `DROP FUNCTION "schema"."name"` (the reverse of creating a routine).

    No argument signature: in Postgres the name is enough as long as the routine is not
    overloaded (scope: one routine per name).
    """
    routine_ref = qualified(routine.schema, routine.name, dialect)
    return f"DROP FUNCTION {routine_ref}"


def sql_type_of(column: SnakeColumnInfo, dialect: SnakeDialect) -> str:
    """The COMPLETE SQL type of a column, parameters included.

    It is the only thing it makes sense to compare two versions of a column with:
    looking at `python_type` alone gave `NUMERIC(10,2)` == `NUMERIC(12,2)` (both of them
    `Decimal`) and lost the change of precision. Comparing the resulting type covers any
    parameterized type to come.

    NOTHING is concatenated here. It used to be: the precision was glued to the type
    with an f-string, OUTSIDE the dialect, and that was the hole — the only parameter
    that did not go through `map_type` was also the only one nobody validated, and a
    `precision` on a `str` emitted `TEXT(12,2)` that only blew up on the `migrate`. The
    dialect returns the whole type or it does not return it.
    """
    return dialect.map_type(
        column.storage_type,
        autoincrement=column.autoincrement,
        params=column.type_params,
    )


def _column_def(column: SnakeColumnInfo, dialect: SnakeDialect) -> str:
    """Defines a column: `"name" TYPE [NOT NULL] [DEFAULT x] [COMMENT '...']`.

    The `COMMENT` only appears on an engine that spells comments as a clause, and it is appended in
    BOTH branches on purpose: the autoincrement one returns early, and leaving it out there would
    have dropped the comment of every surrogate primary key without a word.
    """
    sql_type = sql_type_of(column, dialect)
    parts = [dialect.quote_ident(column.name), sql_type]
    if not column.autoincrement:
        # The autoincrement type already implies NOT NULL and brings its own value.
        if not column.nullable:
            parts.append("NOT NULL")
        expression = _default_expr(column, dialect)
        if expression is not None:
            parts.append(f"DEFAULT {expression}")
    if _comments_are_inline(dialect) and column.db_comment is not None:
        parts.append(f"COMMENT {dialect.literal(column.db_comment)}")
    # Uniqueness is NOT emitted here: it comes out as a NAMED constraint at table level
    # (see `emit_create_table`), so that the add and the drop use the same identifier.
    return " ".join(parts)


def _default_expr(column: SnakeColumnInfo, dialect: SnakeDialect) -> str | None:
    """SQL expression of the `DEFAULT` of a column, or None if it has none.

    Priority: `server_default` (enum → dialect), `server_default_sql` (raw NOT portable
    SQL), and last the client-side literal `default` (the dialect formats it). The three
    sources are mutually exclusive by construction (the descriptor guarantees it when
    the column is declared).
    """
    if column.server_default is not None:
        return dialect.server_default_sql(column.server_default)
    if column.server_default_sql is not None:
        return column.server_default_sql
    if column.has_default:
        return dialect.literal(column.default)
    return None


def _default_changed(old: SnakeColumnInfo, new: SnakeColumnInfo) -> bool:
    """Tells whether the `DEFAULT` of a column changed (client literal or server)."""
    return (
        old.has_default != new.has_default
        or old.default != new.default
        or old.server_default != new.server_default
        or old.server_default_sql != new.server_default_sql
    )


def _function_name(trigger: SnakeTriggerInfo) -> str:
    """The name of the function a PostgreSQL trigger calls: the trigger's own, plus `_fn`.

    Derived and not declared, so that dropping the trigger knows what to drop without carrying a
    second field that could disagree with the first.
    """
    return f"{trigger.name}_fn"


def _body_already_calls_a_function(body: str) -> bool:
    """Whether the body is already the PostgreSQL shape, so wrapping it would nest a call in a call."""
    return body.strip().upper().startswith(("EXECUTE FUNCTION", "EXECUTE PROCEDURE"))


def emit_create_trigger(trigger: SnakeTriggerInfo, dialect: SnakeDialect) -> list[str]:
    """The statements that create a trigger. ONE on the inline engines, TWO on PostgreSQL.

    The events are emitted in the ORDER DECLARED (reordering them adds noise to the diff without
    gaining anything).

    THE BODY IS WRITTEN ONCE AND THE DIALECT SPELLS IT. PostgreSQL cannot hold statements in a
    trigger — it calls a function — while MySQL and SQLite cannot call one. Sending the body through
    verbatim made a declaration that ran on two engines fail on the third with `syntax error at or
    near "UPDATE"`, from the driver, about a token. Translating spelling is exactly what a dialect is
    for, and there is precedent one file over: SQLite has no `CREATE OR REPLACE VIEW` and the dialect
    rewrites it as `DROP` + `CREATE`.

    A body that ALREADY calls a function is left alone. The dialect translates what needs
    translating; it does not second-guess somebody who wrote the target shape on purpose.
    """
    quote = dialect.quote_ident
    events = " OR ".join(event.value for event in trigger.events)
    scope = "FOR EACH ROW" if trigger.for_each_row else "FOR EACH STATEMENT"
    table = qualified(trigger.schema, trigger.table, dialect)

    before, body = dialect.trigger_statements(trigger.name, trigger.body)
    statements: list[str] = list(before)
    statements.append(
        f"CREATE TRIGGER {quote(trigger.name)} {trigger.timing.value} {events} "
        f"ON {table} {scope} {body}"
    )
    return statements


def emit_drop_trigger(trigger: SnakeTriggerInfo, dialect: SnakeDialect) -> list[str]:
    """The statements that drop a trigger, INCLUDING the function it was given on PostgreSQL.

    In Postgres a trigger belongs to a table (its name is not unique), so the `ON` is needed; in
    SQLite it is a global object and the `ON` is invalid syntax. A difference of SYNTAX, not of
    capability, so it gets translated here (same criterion as the UNIQUE constraint → unique index).

    And on PostgreSQL the function goes with it. `emit_create_trigger` wraps an inline body in one, so
    leaving it behind would be debris a rolled-back migration never cleans up — invisible until a name
    collides. The trigger goes FIRST: it depends on the function, and getting that order wrong fails
    only on rollback, which is the run nobody watches.

    `IF EXISTS` on the function because a body that already called one was never wrapped, so there may
    be nothing of ours to drop.
    """
    quote = dialect.quote_ident
    if not dialect.triggers_are_table_scoped:
        statements = [f"DROP TRIGGER {quote(trigger.name)}"]
    else:
        table = qualified(trigger.schema, trigger.table, dialect)
        statements = [f"DROP TRIGGER {quote(trigger.name)} ON {table}"]

    # Whatever the dialect creates BEFORE the trigger has to come back down with it. Asking the
    # dialect again — rather than remembering what it did — is what keeps the two halves from
    # disagreeing the day an engine starts or stops needing one.
    before, _ = dialect.trigger_statements(trigger.name, trigger.body)
    if before:
        statements.append(f"DROP FUNCTION IF EXISTS {quote(_function_name(trigger))}()")
    return statements
