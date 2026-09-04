"""CHECK constraints: domain rules declared TYPED and verified by the database.

Django makes you write `CheckConstraint(check=Q(age__gte=18))` with magic strings no checker
understands. Here the condition is the SAME `SnakeCondition` that `.filter()` already uses, so
`User.age >= 18` is checked at type time: rename the column and it stops compiling.

The full 4-point contract is covered —metadata, renderer, diff+operation and DDL emitter—, which is
the only thing that stops a new structure ending up as dead metadata the way `db_comment` did.
"""

from __future__ import annotations

import pytest

from snakeorm.dialects import PostgresDialect, SQLiteDialect
from snakeorm.dialects.capabilities import Cap
from snakeorm.core.exceptions import SnakeMigrationError, SnakeModelDefinitionError
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import (
    AddCheck,
    DropCheck,
    RebuildTable,
    SchemaState,
    diff_schema,
    emit_add_check,
    emit_create_table,
    emit_drop_check,
    realize,
)

_DIALECT = PostgresDialect()
_ID = SnakeColumnInfo(name="id", python_type=int)
_AGE = SnakeExpr[int](path=("age",))
_NAME = SnakeExpr[str](path=("name",))

_ADULT = SnakeCheckInfo(condition=_AGE >= 18)


def _table(*checks: SnakeCheckInfo) -> SnakeTableInfo:
    """The 'users' table (id, age, name) with the given checks."""
    return SnakeTableInfo(
        name="users",
        columns=(
            _ID,
            SnakeColumnInfo(name="age", python_type=int),
            SnakeColumnInfo(name="name", python_type=str),
        ),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        checks=checks,
    )


def test_the_name_is_derived_from_the_columns_it_mentions() -> None:
    """Verifies the default name `ck_{table}_{columns}`, in line with `ix_` and `uq_`."""
    assert _ADULT.resolved_name("users") == "ck_users_age"
    combined = SnakeCheckInfo(condition=(_AGE >= 18) & (_NAME != ""))
    assert combined.resolved_name("users") == "ck_users_age_name"


def test_an_explicit_name_wins() -> None:
    """Verifies that an explicit name overrules the derived one (same criterion as the indexes)."""
    named = SnakeCheckInfo(condition=_AGE >= 18, name="mayoria_de_age")
    assert named.resolved_name("users") == "mayoria_de_age"


def test_a_column_mentioned_twice_appears_once_in_the_name() -> None:
    """Verifies that the name does not repeat columns: `age > 0 AND age < 150` is `ck_users_age`."""
    rango = SnakeCheckInfo(condition=(_AGE > 0) & (_AGE < 150))
    assert rango.resolved_name("users") == "ck_users_age"


def test_create_table_inlines_the_check() -> None:
    """Verifies that the CHECK goes into the `CREATE TABLE`, with its own name and no placeholders."""
    ddl = emit_create_table(_table(_ADULT), _DIALECT)
    assert 'CONSTRAINT "ck_users_age" CHECK ("age" >= 18)' in ddl
    assert "%s" not in ddl


def test_add_and_drop_are_inverse() -> None:
    """Verifies that the add and the drop attack the SAME name (the lesson from uniqueness)."""
    table = _table(_ADULT)
    assert emit_add_check(table, _ADULT, _DIALECT) == (
        'ALTER TABLE "public"."users" ADD CONSTRAINT "ck_users_age" CHECK ("age" >= 18)'
    )
    assert emit_drop_check(table, _ADULT, _DIALECT) == (
        'ALTER TABLE "public"."users" DROP CONSTRAINT "ck_users_age"'
    )


def test_diff_detects_a_new_check() -> None:
    """Verifies that adding a check to an existing table produces a RebuildTable (not silence).

    IT USED TO SAY `AddCheck`, and the change is the point rather than a detail. A CHECK on a table
    that already exists is a change SQLite can make no other way than by remaking the table around
    it, so the migration file names the rebuild instead of naming a statement one of the three
    engines cannot run. What this test has always guarded — that the change is not met with silence —
    is unmoved; what moved is which operation carries it. `AddCheck` still exists and still applies:
    twenty migrations of the demos are written with it.
    """
    operations = diff_schema([_table()], [_table(_ADULT)])
    assert len(operations) == 1
    rebuild = operations[0]
    assert isinstance(rebuild, RebuildTable)
    assert [check.resolved_name("users") for check in rebuild.after.checks] == [
        "ck_users_age"
    ]
    assert rebuild.before.checks == ()


def test_diff_detects_a_removed_check() -> None:
    """Verifies that removing a check produces a rebuild that no longer carries it."""
    operations = diff_schema([_table(_ADULT)], [_table()])
    assert len(operations) == 1
    rebuild = operations[0]
    assert isinstance(rebuild, RebuildTable)
    assert rebuild.after.checks == ()
    assert rebuild.before.checks == (_ADULT,), "the reverse needs the check it took out"


def test_diff_recreates_a_changed_condition() -> None:
    """Verifies that changing the condition under the same name recreates the constraint (drop + add).

    SQL does not alter a CHECK in place: it has to be dropped and created again. That has not
    changed — it moved one level down, from two operations in the file into the two statements the
    one operation emits, which is where the engines differ about it.
    """
    stricter = SnakeCheckInfo(condition=_AGE >= 21)
    operations = diff_schema([_table(_ADULT)], [_table(stricter)])
    assert [type(op).__name__ for op in operations] == ["RebuildTable"]

    statements = operations[0].up_sql(_DIALECT)
    assert 'DROP CONSTRAINT "ck_users_age"' in statements[0]
    assert 'ADD CONSTRAINT "ck_users_age" CHECK ("age" >= 21)' in statements[1]


def test_a_check_change_alongside_a_column_change_keeps_the_old_operations() -> None:
    """Verifies the rebuild only takes over when the constraint is the table's ONLY change.

    A rebuild that also swallowed the column operations would take `rename_suggestions` with it —
    the warning that stops a `DropColumn` + `AddColumn` pair from deleting a column's data reads
    exactly those two out of the diff. Going quiet there, on tables that HAVE constraints, is a net
    that fails open, and this branch has already deleted three of those.
    """
    with_column = SnakeTableInfo(
        name="users",
        columns=(*_table().columns, SnakeColumnInfo(name="nickname", python_type=str)),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        checks=(_ADULT,),
    )

    kinds = [type(op).__name__ for op in diff_schema([_table()], [with_column])]

    assert "RebuildTable" not in kinds
    assert kinds == ["AddColumn", "AddCheck"]


def test_an_identical_check_converges() -> None:
    """Verifies that an identical check produces no operations: the autogen has to converge."""
    assert (
        diff_schema([_table(_ADULT)], [_table(SnakeCheckInfo(condition=_AGE >= 18))])
        == []
    )


def test_a_new_table_does_not_emit_add_check() -> None:
    """Verifies that a new table does not duplicate: its CREATE TABLE already carries the checks."""
    operations = diff_schema([], [_table(_ADULT)])
    assert len(operations) == 1
    assert not isinstance(operations[0], AddCheck)


def test_operations_mutate_the_state() -> None:
    """Verifies `apply_to_state`, without which the autogen replay does not converge."""
    state = SchemaState([_table()])
    AddCheck(_table(_ADULT), _ADULT).apply_to_state(state)
    stored = state.get_table("users")
    assert stored is not None and stored.checks == (_ADULT,)

    DropCheck(_table(_ADULT), _ADULT).apply_to_state(state)
    assert state.get_table("users").checks == ()  # type: ignore[union-attr]


# --- What the engine that cannot do it SAYS, which is the only thing the user gets ----------
#
# SQLite has no `ALTER TABLE ... ADD/DROP CONSTRAINT`, so `realize` stops the plan. The two halves
# of the pair used to answer differently: `DropCheck` EXPLAINED the limit and `AddCheck` PRESCRIBED
# "declare it before creating the table" — an instruction that cannot be carried out once the table
# exists in a migration history, because it points at a migration already applied. A refusal that
# sends you somewhere you cannot go is worse than a plain "I cannot": it costs the reader the time
# it takes to discover the door is walled up.


_CAN_ADD_A_CHECK = SQLiteDialect().capabilities.can(Cap.CHECK_CONSTRAINT_DDL)
"""Whether THIS SQLite adds a CHECK to a standing table: it learned how in 3.53.

The tests below read the REFUSAL, so where there is none they skip instead of asserting a lifted
limit."""

_ONLY_WHEN_REFUSED = pytest.mark.skipif(
    _CAN_ADD_A_CHECK,
    reason="this SQLite adds the CHECK, so there is no refusal to inspect",
)


@_ONLY_WHEN_REFUSED
def test_sqlite_refuses_to_add_a_check_and_explains_the_limit() -> None:
    """Verifies the refusal names the engine limit and the rebuild it would take, not a prescription."""
    with pytest.raises(SnakeMigrationError) as error:
        realize([AddCheck(_table(_ADULT), _ADULT)], SQLiteDialect())

    message = str(error.value)
    assert "add a constraint to an existing table" in message
    assert "rebuilding the whole table" in message


@_ONLY_WHEN_REFUSED
def test_the_add_check_refusal_offers_the_way_out_the_user_actually_has() -> None:
    """Verifies it points at `RebuildTable`, the door open today, and never at the past.

    "Declare it before creating the table" was the first wording, and it is unreachable advice for
    the table this operation is about: that table already exists, and its `CreateTable` is a
    migration somebody already ran. Pinning the sentence as ABSENT is the regression this test
    exists for.

    THE SECOND WORDING AGED TOO, and less visibly. It said the rebuild "is the user's call, not the
    ORM's: do it with an explicit `RunSQL`" — true when it was written, and false since
    `RebuildTable` exists, is imported by `realize` itself, and is what the diff collapses a pure
    constraint change into. An instruction to hand-write SQL the ORM already emits is not wrong
    about the engine; it is wrong about this ORM, which is the harder kind to notice.
    """
    with pytest.raises(SnakeMigrationError) as error:
        realize([AddCheck(_table(_ADULT), _ADULT)], SQLiteDialect())

    message = str(error.value)
    assert "RebuildTable" in message
    assert "declare it before creating the table" not in message
    assert "the user's call, not the ORM's" not in message


def test_the_add_check_prescription_is_accepted_by_the_engine_that_refused() -> None:
    """Verifies the plan the refusal describes passes the very gate that rejected the `AddCheck`.

    A message cannot be tested for being honest, but the plan it prescribes can be built and handed
    back to `realize` on the same engine. That is the mechanical half of the promise, and it is the
    check the old `RunSQL` wording could never have passed: a `RunSQL` is opaque to the planner.
    """
    rebuild = RebuildTable(_table(), _table(_ADULT))

    assert realize([rebuild], SQLiteDialect()) == [rebuild]


@_ONLY_WHEN_REFUSED
def test_both_halves_of_the_pair_name_the_same_engine_limit() -> None:
    """Verifies `AddCheck` and `DropCheck` describe ONE gap and ONE way out, because there is one.

    They are the two doors of the same missing `ALTER TABLE ... ADD/DROP CONSTRAINT`, and a user who
    meets them in the same migration reads both. Asserting one against the other is what keeps them
    from drifting into two different stories about the same engine — which is exactly what happened
    while nothing compared them.

    The way out is now asserted alongside the limit, because that is the half that drifted last:
    `DropCheck` described the rebuild and `AddCheck` prescribed hand-written SQL for it.
    """
    messages: list[str] = []
    for operation in (
        AddCheck(_table(_ADULT), _ADULT),
        DropCheck(_table(_ADULT), _ADULT),
    ):
        with pytest.raises(SnakeMigrationError) as error:
            realize([operation], SQLiteDialect())
        messages.append(str(error.value))

    for message in messages:
        assert "constraint" in message
        assert "rebuilding the whole table" in message
        assert "RebuildTable" in message


def test_a_check_with_a_subquery_is_rejected_when_declared() -> None:
    """Verifies that a non-renderable condition fails ON DECLARATION, not when migrating.

    Failing where the mistake is written is half the value of an error. Postgres does not accept
    subqueries in a CHECK either, so the rejection is correctness and not a limitation of ours.
    """
    from snakeorm.expressions import SnakeSubquery
    from snakeorm.fields import snake_check

    subquery: SnakeSubquery[int] = SnakeSubquery(schema="public", name="t", column="c")
    with pytest.raises(
        SnakeModelDefinitionError,
        match="SnakeInSubquery cannot be written into a migration file: it",
    ):
        snake_check(_AGE.in_(subquery))
