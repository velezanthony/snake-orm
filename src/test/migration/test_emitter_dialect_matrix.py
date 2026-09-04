"""EVERY DDL emitter, against EVERY engine. The fifth parity net.

This project carries a pattern of bugs that repeats with an almost comical regularity: **something
implemented or verified in N-1 out of N siblings**. Foreign keys existed in Postgres and not in
SQLite. Migrations worked in Postgres and would not even start in SQLite. `AsyncSession` shipped
with twelve of twenty-two methods. The types had the DDL and not the runtime.

And the only thing that has caught that class reliably are tests with THE SAME structure: enumerate
the surfaces from the code itself and demand parity. There are four already —operation completeness,
AST parity of the sessions, type round-trip, and the anti-skip net—. This is the fifth, and it
covers the biggest surface that was left: **every DDL emitter by two engines, of which only a
third was verified on both**. The count is not written down here on purpose: the parametrisations
below read it off `_INVOCATIONS`, and a figure in prose is the half that stops being true — this
file said twenty-four for as long as `emit_rebuild_table` and `emit_rename_table` had been in it.

Measured before writing it: of the five emitters tried by hand against SQLite, FOUR emitted invalid
SQL (`near "CONSTRAINT"`, `near "SCHEMA"`, `near "COMMENT"`, `near "ALTER"`). And the dialect
already declared `supports_add_constraint`, `supports_schemas`, `supports_comments` and
`supports_alter_column` as `False` — the flags were there, nobody read them. Exactly the state
`supports_add_constraint` was in the morning it was discovered that the FKs did not exist.

**What is demanded.** Not that everything work on every engine: that would be false. What is
demanded is that each emitter do ONE of two things, and nothing else:

1. Emit SQL the engine ACCEPTS, or
2. be covered by `realize()`, which stops it in the PLAN with a readable reason.

What stays forbidden is the third option, which is the one that was there: emitting SQL the engine
rejects, so that it blows up with a cryptic syntax error in the middle of a deployment.
"""

from __future__ import annotations

from collections.abc import Iterator

from collections.abc import Callable

import pytest

from snakeorm.drivers.base import SnakeDriver
from test.scenarios.engines import DIALECTS, three_drivers

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    SnakeDialect,
    SnakeExpr,
    SQLiteDialect,
    SQLiteDriver,
)
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.dialects.capabilities import PLAN_CAPS
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeRoutineInfo,
    SnakeTableInfo,
    SnakeTableKind,
    SnakeTriggerEvent,
    SnakeTriggerInfo,
    SnakeTriggerTiming,
)
from snakeorm.migration import ddl

_ID = SnakeColumnInfo(name="id", python_type=int)
_NAME = SnakeColumnInfo(name="name", python_type=str, nullable=True)
_PARENT = SnakeTableInfo(
    name="mx_parents", columns=(_ID,), primary_key=SnakePrimaryKeyInfo(columns=(_ID,))
)
_REL = SnakeRelationshipInfo(
    name="parent",
    target="Parent",
    kind=SnakeRelationshipKind.TO_ONE,
    foreign_key=SnakeForeignKeyInfo(target="Parent", pairs=(("parent_id", "id"),)),
    target_table="public.mx_parents",
)
_CHILD = SnakeTableInfo(
    name="mx_children",
    columns=(_ID, _NAME, SnakeColumnInfo(name="parent_id", python_type=int)),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    relationships=(_REL,),
)
_COMMENTED = SnakeTableInfo(
    name="mx_children",
    columns=(_ID,),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    db_comment="a commented table",
)
_NEW = SnakeTableInfo(
    name="mx_nuevas", columns=(_ID,), primary_key=SnakePrimaryKeyInfo(columns=(_ID,))
)
"""Table the fixture does NOT create: it is the one `emit_create_table` uses so as not to clash."""
_EXTRA = SnakeColumnInfo(name="extra", python_type=str, nullable=True)
_CHECK = SnakeCheckInfo(condition=SnakeExpr[int](path=("id",)) > 0, name="ck_mx")
_CHECKED_PARENT = SnakeTableInfo(
    name="mx_parents",
    columns=(_ID,),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    checks=(_CHECK,),
)
"""`mx_parents` wearing a CHECK: the `after` half of the rebuild's invocation."""
_INDEX = SnakeIndexInfo(columns=("id",), name="ix_mx_name")
_VIEW = SnakeTableInfo(
    name="mx_vista",
    columns=(_ID,),
    primary_key=SnakePrimaryKeyInfo(columns=()),
    kind=SnakeTableKind.VIEW,
    view_definition='SELECT "id" FROM "mx_children"',
)
_NEW_INDEX = SnakeIndexInfo(columns=("parent_id",), name="ix_mx_parent")
_NEW_VIEW = SnakeTableInfo(
    name="mx_vista_nueva",
    columns=(_ID,),
    primary_key=SnakePrimaryKeyInfo(columns=()),
    kind=SnakeTableKind.VIEW,
    view_definition='SELECT "id" FROM "mx_children"',
)
_NEW_TRIGGER = SnakeTriggerInfo(
    name="mx_tg_nuevo",
    table="mx_children",
    timing=SnakeTriggerTiming.AFTER,
    events=(SnakeTriggerEvent.INSERT,),
    body="BEGIN SELECT 1; END",
)
_ROUTINE = SnakeRoutineInfo(
    name="mx_f", body="CREATE FUNCTION mx_f() RETURNS int AS 'SELECT 1'"
)
_TRIGGER = SnakeTriggerInfo(
    name="mx_tg",
    table="mx_children",
    timing=SnakeTriggerTiming.AFTER,
    events=(SnakeTriggerEvent.INSERT,),
    body="BEGIN SELECT 1; END",
)

# One invocation of EACH emitter. That this table be complete is what the first test watches: if a
# new emitter shows up with no entry here, it fails and forces one in. The list of emitters is
# taken from the MODULE, never from this table — it is the lesson of the four previous nets.
_INVOCATIONS: dict[str, Callable[[SnakeDialect], list[str]]] = {
    "emit_create_table": lambda d: [ddl.emit_create_table(_NEW, d)],
    "emit_drop_table": lambda d: [ddl.emit_drop_table(_CHILD, d)],
    "emit_add_column": lambda d: [ddl.emit_add_column(_CHILD, _EXTRA, d)],
    "emit_drop_column": lambda d: [ddl.emit_drop_column(_CHILD, "name", d)],
    "emit_rename_column": lambda d: [
        ddl.emit_rename_column(_CHILD, "name", "apodo", d)
    ],
    "emit_rename_table": lambda d: [ddl.emit_rename_table(_CHILD, "renamed", d)],
    # Over the PARENT and not the child: on SQLite the rebuild drops and recreates the table, and
    # `mx_children` carries a view and a trigger that the drop would take with it — the fixture's
    # own scaffolding failing, not the emitter. The parent has neither, and it is the table with a
    # key pointing AT it, which is the half that has to survive.
    "emit_rebuild_table": lambda d: ddl.emit_rebuild_table(_PARENT, _CHECKED_PARENT, d),
    "emit_alter_column": lambda d: ddl.emit_alter_column(_CHILD, _NAME, _ID, d),
    "emit_create_index": lambda d: [ddl.emit_create_index(_CHILD, _NEW_INDEX, d)],
    "emit_drop_index": lambda d: [ddl.emit_drop_index(_CHILD, _INDEX, d)],
    "emit_add_check": lambda d: [ddl.emit_add_check(_CHILD, _CHECK, d)],
    "emit_drop_check": lambda d: [ddl.emit_drop_check(_CHILD, _CHECK, d)],
    "emit_add_foreign_key": lambda d: [
        ddl.emit_add_foreign_key(_CHILD, _REL, _PARENT, d)
    ],
    "emit_drop_foreign_key": lambda d: [ddl.emit_drop_foreign_key(_CHILD, _REL, d)],
    "emit_create_schema": lambda d: [ddl.emit_create_schema("analytics", d)],
    "emit_drop_schema": lambda d: [ddl.emit_drop_schema("analytics", d)],
    "emit_table_comment": lambda d: [ddl.emit_table_comment(_COMMENTED, d)],
    "emit_column_comment": lambda d: [ddl.emit_column_comment(_CHILD, _ID, d)],
    "emit_comments": lambda d: ddl.emit_comments(_COMMENTED, d),
    "emit_create_view": lambda d: [ddl.emit_create_view(_NEW_VIEW, d)],
    "emit_drop_view": lambda d: [ddl.emit_drop_view(_VIEW, d)],
    "emit_replace_view": lambda d: [ddl.emit_replace_view(_VIEW, d)],
    "emit_create_function": lambda d: [ddl.emit_create_function(_ROUTINE, d)],
    "emit_drop_function": lambda d: [ddl.emit_drop_function(_ROUTINE, d)],
    "emit_create_trigger": lambda d: ddl.emit_create_trigger(_NEW_TRIGGER, d),
    "emit_drop_trigger": lambda d: ddl.emit_drop_trigger(_TRIGGER, d),
}

# Emitters SQLite cannot execute, with the dialect flag that already declares it. It is not a list
# of excuses: it is the contract. Each one has to be stopped by `realize()` in the plan, and the
# second test demands it — if any of them slips through to the engine, it fails.
_IMPOSSIBLE_IN_SQLITE: dict[str, str] = {
    "emit_add_check": "supports_add_constraint",
    "emit_drop_check": "supports_add_constraint",
    "emit_add_foreign_key": "supports_add_constraint",
    "emit_drop_foreign_key": "supports_add_constraint",
    "emit_alter_column": "supports_alter_column",
    "emit_create_schema": "supports_schemas",
    "emit_drop_schema": "supports_schemas",
    "emit_table_comment": "supports_comments",
    "emit_column_comment": "supports_comments",
    # `emit_comments` is NOT here: it gets TRANSLATED to an empty list. A comment is documentation
    # for humans, not integrity, so losing it on an engine that does not store them is correct —
    # refusing to migrate over a `db_comment` would leave the ORM useless on SQLite.
    # A FUNCTION is not an object of SQLite: there is no `CREATE FUNCTION`. The body is written by
    # the user in the dialect of their engine, so this was never portable and it is not faked to be.
    "emit_replace_view": "supports_replace_view",
    "emit_create_function": "no equivalent",
    "emit_drop_function": "no equivalent",
}


def _emitters() -> list[str]:
    """The emitters that exist, read from the MODULE and not from a hand-written list."""
    return sorted(
        name
        for name in vars(ddl)
        if name.startswith("emit_")
        and callable(obj := getattr(ddl, name))
        and getattr(obj, "__module__", "") == ddl.__name__
    )


def test_the_invocation_table_covers_every_emitter() -> None:
    """If a new emitter shows up, this test says so BEFORE a deployment fails.

    It is the half that makes the rest useful: a matrix over an incomplete list passes just as
    green, and that trap already showed up several times in this branch.
    """
    missing = set(_emitters()) - set(_INVOCATIONS)

    assert missing == set(), (
        f"emitters with no invocation in the matrix: {sorted(missing)}"
    )


@pytest.fixture
def sqlite() -> Iterator[SQLiteDriver]:
    """A SQLite database with the matrix tables already created, to run the DDL for real."""
    driver = SQLiteDriver.connect(":memory:")
    dialect = SQLiteDialect()
    try:
        driver.execute(ddl.emit_create_table(_PARENT, dialect), ())
        driver.execute(ddl.emit_create_table(_CHILD, dialect), ())
        # The DROP emitters need to find what they drop, or the error would be the fixture's and not
        # the emitter's — and a test that fails because of its own scaffolding measures nothing.
        driver.execute(ddl.emit_create_index(_CHILD, _INDEX, dialect), ())
        driver.execute(ddl.emit_create_view(_VIEW, dialect), ())
        for statement in ddl.emit_create_trigger(_TRIGGER, dialect):
            driver.execute(statement, ())
        yield driver
    finally:
        driver.close()


@pytest.mark.parametrize("emitter", sorted(_INVOCATIONS), ids=str)
def test_what_sqlite_can_run_it_actually_runs(
    emitter: str, sqlite: SQLiteDriver
) -> None:
    """What is NOT declared impossible, the engine ACCEPTS. Executed, not read.

    Checking the emitted string would measure the emitter against itself. The only thing that proves
    a DDL is valid is that the database swallows it, which is the lesson written down in
    `test_render_completeness.py` and the one the JSON dodged for months.
    """
    if emitter in _IMPOSSIBLE_IN_SQLITE:
        pytest.skip(
            f"SQLite cannot: {_IMPOSSIBLE_IN_SQLITE[emitter]} (`realize` stops it)"
        )

    for statement in _INVOCATIONS[emitter](SQLiteDialect()):
        sqlite.execute(statement, ())


@pytest.mark.parametrize("emitter", sorted(_IMPOSSIBLE_IN_SQLITE), ids=str)
def test_what_sqlite_cannot_run_really_cannot(
    emitter: str, sqlite: SQLiteDriver
) -> None:
    """The control: what is declared impossible REALLY is.

    Without this, the list of exceptions would turn into a drawer for stashing whatever annoys. If
    some day SQLite accepts one of these —or the emitter learns to translate it, as already happened
    with the UNIQUE constraint—, this test fails and forces it out of the list.
    """
    with pytest.raises(Exception):  # noqa: B017 - the engine raises its own syntax error
        for statement in _INVOCATIONS[emitter](SQLiteDialect()):
            sqlite.execute(statement, ())


@pytest.mark.parametrize("emitter", sorted(_INVOCATIONS), ids=str)
def test_postgres_can_emit_every_one_of_them(emitter: str) -> None:
    """The other engine emits every one of them without blowing up: the symmetric half of the matrix.

    They are not run against a server: the Postgres DDL is already covered by `test/integration/`.
    What is checked here is that no emitter assumes capabilities its own dialect does not declare.
    """
    statements = _INVOCATIONS[emitter](PostgresDialect())

    assert statements and all(isinstance(s, str) and s for s in statements)


# The same as `_IMPOSSIBLE_IN_SQLITE`, for the third engine. Each one is stopped by `realize()` in
# the plan, or guarded by its caller reading the capability before invoking it.
_IMPOSSIBLE_IN_MYSQL: dict[str, str] = {
    "emit_create_schema": "SCHEMAS",
    "emit_drop_schema": "SCHEMAS",
    # `emit_table_comment` and `emit_column_comment` USED to be here, and the entry read "COMMENTS"
    # while the note beside it said "MySQL comments INLINE (`COLUMN ... COMMENT`)" — a sentence
    # about grammar filed as an engine that cannot. Measured, MariaDB stores both comments and
    # replaces them; the two emitters now translate into the inline spelling, so the drawer this
    # file's own docstring warns about lost two entries.
    "emit_create_function": "STORED_FUNCTIONS",
    "emit_drop_function": "STORED_FUNCTIONS",
}

# `emit_comments` gets TRANSLATED to an empty list, and on the two engines for DIFFERENT reasons.
# SQLite stores no comment at all, and a comment is documentation rather than integrity, so refusing
# to migrate over a `db_comment` would leave the ORM useless there. MySQL stores them fine: they
# already travelled INSIDE the `CREATE TABLE`, so a second statement would write each one twice.
_TRANSLATE_TO_EMPTY = frozenset({"emit_comments"})


@pytest.mark.parametrize("emitter", sorted(_INVOCATIONS), ids=str)
def test_mysql_can_emit_every_one_of_them(emitter: str) -> None:
    """The THIRD engine emits every one of them. It is the leg that was missing, and not by chance.

    This matrix was Postgres × SQLite, and the docstring above denounces the pattern "implemented or
    verified in N-1 out of N siblings" — while the absent sibling was precisely MySQL, the one with
    the broken grammar. `rg -i mysql src/test/migration/` returned not a single result.
    """
    if emitter in _IMPOSSIBLE_IN_MYSQL:
        pytest.skip(f"MySQL cannot: {_IMPOSSIBLE_IN_MYSQL[emitter]}")

    statements = _INVOCATIONS[emitter](MySQLDialect())

    assert all(isinstance(s, str) and s for s in statements)
    assert statements or emitter in _TRANSLATE_TO_EMPTY


# Constructions that belong to ANOTHER engine. An emitter that smuggles them into MySQL emits SQL
# the server rejects, which is exactly the third option this file forbids.
_FOREIGN_TO_MYSQL = ("ALTER COLUMN", "::", "COMMENT ON")


@pytest.mark.parametrize("emitter", sorted(_INVOCATIONS), ids=str)
def test_no_emitter_writes_postgres_grammar_for_mysql(emitter: str) -> None:
    """No emitter writes MySQL a construction only Postgres understands.

    It is checked over EVERY entry of `_INVOCATIONS` and not over the two that were known broken:
    the value of a matrix is catching the one nobody has looked at yet. `emit_alter_column` wired in
    `ALTER COLUMN ... USING` and `emit_drop_index` omitted the `ON table`; both went through here
    with nothing watching.
    """
    if emitter in _IMPOSSIBLE_IN_MYSQL:
        pytest.skip(f"MySQL cannot: {_IMPOSSIBLE_IN_MYSQL[emitter]}")

    emitted = " ".join(_INVOCATIONS[emitter](MySQLDialect()))

    for construct in _FOREIGN_TO_MYSQL:
        assert construct not in emitted, (
            f"{emitter} writes MySQL a {construct!r}, which is Postgres syntax"
        )


def test_what_mysql_cannot_do_is_stopped_by_the_plan_too() -> None:
    """What MySQL cannot do is stopped in the PLAN too, not halfway through the `migrate`.

    It matters more here than in SQLite: MySQL has no transactional DDL, so a failure halfway
    through a migration leaves the previous steps applied and there is no rollback to undo them.
    """
    from snakeorm.migration import CreateFunction, CreateSchema, realize

    for operation in (CreateSchema("analytics"), CreateFunction(_ROUTINE)):
        with pytest.raises(
            SnakeMigrationError,
            match="this engine has no named schemas|this engine has no stored functions",
        ):
            realize([operation], MySQLDialect())


def test_every_impossible_emitter_is_stopped_by_the_plan_not_by_the_engine() -> None:
    """What SQLite cannot do is stopped in the PLAN, with its reason, not halfway through the `migrate`.

    It is the difference between `SnakeMigrationError: SQLite no soporta ALTER COLUMN; reconstruye
    la tabla` while generating the plan, and `OperationalError: near "ALTER": syntax error` while
    deploying at eleven at night. The SQL is invalid in both cases; what changes is when it is known
    and whether the message is of any use.
    """
    from snakeorm.migration import AlterColumn, CreateSchema, realize

    for operation in (CreateSchema("analytics"), AlterColumn(_CHILD, _NAME, _ID)):
        with pytest.raises(
            SnakeMigrationError,
            match="SQLite|this engine|does not support|does not allow",
        ):
            realize([operation], SQLiteDialect())


def test_every_plan_capability_has_a_consumer() -> None:
    """Every capability of `PLAN_CAPS` is CONSULTED by somebody. Otherwise it is dead metadata.

    This is the test that closes the whole class of bug, and it exists because it already happened
    twice with the same shape: `db_comment` was captured, stored and tested, and nothing ever
    emitted a `COMMENT ON`; and `supports_add_constraint` was declared in the three dialects without
    a single line reading it — while the foreign keys simply did not exist in SQLite.

    A capability nobody consults is not a declared capability: it is a promise that the ORM takes
    that into account, and it does not.

    It is checked only over `PLAN_CAPS` on purpose. The `ADVISORY_CAPS` need not have a reader
    —they exist so that the startup warning counts them, and walking the whole catalog already
    takes care of that—, so demanding one would force inventing fake readings.

    The previous version of this test looked at `dir(SQLiteDialect)` and searched for the flag name
    as a SUBSTRING. With the capabilities in a catalog that would have kept passing green without
    checking anything: the names now live in two forms (`Cap.UPSERT` and the `supports_upsert`
    bridge), and it is enough for ONE to show up anywhere, even inside a comment. That is why both
    forms are searched explicitly and it says which one was found.
    """
    import pathlib

    source = "\n".join(
        p.read_text()
        for p in pathlib.Path("src/snakeorm").rglob("*.py")
        # Where they are DECLARED does not count as reading them, and neither does the bridge:
        # `DerivedFlags` translates them all by construction, so counting it would always be green.
        if "dialects" not in p.parts
    )
    unread = {
        cap.name
        for cap in PLAN_CAPS
        if f"Cap.{cap.name}" not in source
        and f"supports_{cap.name.lower()}" not in source
    }

    assert unread == set(), (
        f"PLAN_CAPS capabilities that NOBODY reads: {sorted(unread)}. A capability nobody reads "
        f"is something the ORM claims to take into account and does not: either it gets used, or "
        f"it moves to ADVISORY_CAPS saying it only serves to warn."
    )


# -- The other two, EXECUTED ------------------------------------------------------------------------
#
# The SQLite half above runs the DDL for real; the Postgres and MySQL halves only ever read the
# string. That is the same asymmetry this file's header denounces, one level down: a matrix that
# EXECUTES on one engine and READS on two is a matrix over one engine with two opinions attached.
#
# THE FIXTURE BELOW CREATES NO VIEW, and that is the whole design of it. On PostgreSQL a view over a
# column REFUSES to let that column be altered, so a fixture holding one makes `emit_alter_column`
# fail for the FIXTURE's reason — the exact trap the SQLite fixture's own comment names, and the one
# `emit_rebuild_table` already dodges by targeting the parent. The view emitters are skipped here
# with that written out, and they are not uncovered: `test_compound_as_view.py` creates and queries
# views on the three engines.

_NOT_EXECUTED_HERE = {
    "emit_create_view": "a view blocks ALTER COLUMN on PostgreSQL, so this fixture holds none",
    "emit_drop_view": "the same: there is no view here to drop",
    "emit_create_trigger": "a trigger BODY is engine SQL; one body cannot serve three engines",
    "emit_drop_trigger": "the same, and Cap.STORED_FUNCTIONS stops the plan where they cannot live",
    "emit_create_function": "a routine body is engine SQL",
    "emit_drop_function": "the same",
    "emit_replace_view": "it renders the view BODY, and this fixture holds no view",
}
"""Emitters this half does not run, each with the reason it does not.

Per ENTRY and never per file: an exclusion that covers more than it was written for is the shape
this repository keeps paying for. Every one of these is covered elsewhere, and the reason says where
or why it cannot be.
"""


@pytest.fixture
def served() -> Iterator[dict[str, SnakeDriver]]:
    """Postgres and MySQL with the tables and index created, so the DROP emitters find their target.

    Same reasoning as the SQLite fixture: an emitter that fails because its target was never there
    fails for the fixture's reason, and a test that fails because of its own scaffolding measures
    nothing.
    """
    with three_drivers([]) as drivers:
        opened = {name: drivers[name] for name in ("postgres", "mysql")}
        for name, driver in opened.items():
            dialect = DIALECTS[name]
            _reset(driver, name)
            driver.execute(ddl.emit_create_table(_PARENT, dialect), ())
            driver.execute(ddl.emit_create_table(_CHILD, dialect), ())
            driver.execute(ddl.emit_create_index(_CHILD, _INDEX, dialect), ())
            driver.commit()
        try:
            yield opened
        finally:
            for name, driver in opened.items():
                _reset(driver, name)


def _reset(driver: SnakeDriver, engine: str) -> None:
    """Drops everything the matrix can leave behind, in reverse dependency order.

    The `rollback()` first is not decoration: a statement PostgreSQL refused leaves the transaction
    aborted, and every drop after it would be ignored — so the next test would inherit the objects
    of this one and fail for a reason that is not its own.
    """
    driver.rollback()
    cascade = " CASCADE" if engine == "postgres" else ""
    for name in ("renamed", "mx_new", "mx_children", "mx_parents"):
        driver.execute(f"DROP TABLE IF EXISTS {name}{cascade}", ())
    driver.commit()


_NEEDS_FIRST: dict[str, str] = {
    "emit_drop_check": "emit_add_check",
    "emit_drop_foreign_key": "emit_add_foreign_key",
}
"""A DROP needs its target to exist, and the fixture cannot hold one for both halves.

Creating the constraint in the fixture would make the matching `emit_add_*` fail as a duplicate, so
the pairing is written here instead: the drop runs its own add first. On SQLite the question never
came up — both sides are in `_IMPOSSIBLE_IN_SQLITE`, so neither runs.
"""


@pytest.mark.parametrize("engine", ["postgres", "mysql"])
@pytest.mark.parametrize("emitter", sorted(_INVOCATIONS), ids=str)
def test_what_the_other_two_can_run_they_actually_run(
    emitter: str, engine: str, served: dict[str, SnakeDriver]
) -> None:
    """Executed and not read. The only thing that proves a DDL is valid is the database taking it."""
    if emitter in _NOT_EXECUTED_HERE:
        pytest.skip(f"{engine} cannot: {_NOT_EXECUTED_HERE[emitter]}")
    if engine == "mysql" and emitter in _IMPOSSIBLE_IN_MYSQL:
        pytest.skip(f"MySQL cannot: {_IMPOSSIBLE_IN_MYSQL[emitter]}")

    driver = served[engine]
    dialect = DIALECTS[engine]
    for before in _INVOCATIONS.get(_NEEDS_FIRST.get(emitter, ""), lambda _d: [])(
        dialect
    ):
        driver.execute(before, ())

    for statement in _INVOCATIONS[emitter](dialect):
        driver.execute(statement, ())
    driver.commit()
