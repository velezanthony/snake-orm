"""Foreign keys in an engine that does NOT know how to add them later: they go INSIDE the `CREATE TABLE`.

This came out of an introspection test that asked SQLite for its FKs and found none. It found none
because **they did not exist**: the `ALTER TABLE ... ADD CONSTRAINT` the plan emits is a syntax
error in SQLite, so on that engine the ORM had been emitting foreign keys the database never got to
have. An ORM that declares referential integrity and does not create it is exactly the silent
failure this project is after.

And the flag was already there: `supports_add_constraint` existed in the three dialects and
**nobody read it**. Dead metadata, the same sin as `db_comment` back in the day.

The division of responsibilities does not change: the PLAN of operations is still engine-agnostic
(the diff does not know which dialect there will be) and it is on landing it that the dialect
decides the shape. That is why `realize()` is a single point, and why what cannot be done is said
out loud instead of vanishing from the list.
"""

from __future__ import annotations

import pytest

from snakeorm import PostgresDialect, SQLiteDialect, SQLiteDriver
from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeFkAction,
    SnakeForeignKeyInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeTableInfo,
)
from snakeorm.migration import (
    AddForeignKey,
    CreateTable,
    DropForeignKey,
    DropTable,
    emit_create_index,
    emit_create_table,
    emit_drop_index,
    realize,
)
from snakeorm.migration.operations import SnakeMigrationOperation

_ID = SnakeColumnInfo(name="id", python_type=int)
_CUSTOMERS = SnakeTableInfo(
    name="ifk_customers",
    columns=(_ID,),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
)
_CUSTOMER_ID = SnakeColumnInfo(name="customer_id", python_type=int)
_RELATION = SnakeRelationshipInfo(
    name="customer",
    target="Customer",
    kind=SnakeRelationshipKind.TO_ONE,
    foreign_key=SnakeForeignKeyInfo(
        target="Customer",
        pairs=(("customer_id", "id"),),
        on_delete=SnakeFkAction.CASCADE,
    ),
    target_table="public.ifk_customers",
)
_ORDERS = SnakeTableInfo(
    name="ifk_orders",
    columns=(_ID, _CUSTOMER_ID),
    primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
    relationships=(_RELATION,),
)


def test_a_dialect_that_cannot_alter_gets_the_key_inside_the_create() -> None:
    """In SQLite the `CREATE TABLE` carries the `REFERENCES`: it is the only window to declare it."""
    sql = emit_create_table(_ORDERS, SQLiteDialect())

    assert 'FOREIGN KEY ("customer_id") REFERENCES "ifk_customers" ("id")' in sql
    assert "ON DELETE CASCADE" in sql, "the referential actions travel with the key"


def test_a_dialect_that_can_alter_keeps_the_create_clean() -> None:
    """In Postgres it is NOT inlined: the FK goes at the end, when every table exists.

    It is the control for the previous test. Inlining on both engines would look simpler and would
    break the order: an FK inside the `CREATE TABLE` demands that the target table exist ALREADY,
    and that is why the plan leaves them for the end.
    """
    sql = emit_create_table(_ORDERS, PostgresDialect())

    assert "FOREIGN KEY" not in sql


def test_the_redundant_add_disappears_only_when_the_table_is_created_here() -> None:
    """The `AddForeignKey` of a table created in the SAME plan is redundant: it was emitted inline."""
    plan = realize(
        [CreateTable(_ORDERS), AddForeignKey(_ORDERS, _RELATION, _CUSTOMERS)],
        SQLiteDialect(),
    )

    assert [type(operation).__name__ for operation in plan] == ["CreateTable"]


def test_postgres_keeps_every_operation_untouched() -> None:
    """With an engine that does know how to alter, `realize` touches NOTHING. The plan is the plan."""
    original: list[SnakeMigrationOperation] = [
        CreateTable(_ORDERS),
        AddForeignKey(_ORDERS, _RELATION, _CUSTOMERS),
    ]

    assert realize(original, PostgresDialect()) == original


def test_adding_a_key_to_an_existing_table_fails_out_loud() -> None:
    """Adding an FK to a table that ALREADY exists cannot be done in SQLite, and that is said.

    It is the case that justifies `realize` not being a `filter`: filtering in silence would leave
    the user with a green migration and a database without the integrity they asked for. SQLite
    forces rebuilding the whole table, and that is a decision for the user, not something done on
    their behalf.
    """
    with pytest.raises(
        SnakeMigrationError,
        match="does not know how to add constraints to an existing table",
    ):
        realize([AddForeignKey(_ORDERS, _RELATION, _CUSTOMERS)], SQLiteDialect())


def test_dropping_a_key_along_with_its_table_is_not_an_error() -> None:
    """If the whole table goes, its FK goes with it: there is nothing to remove separately."""
    plan = realize(
        [DropForeignKey(_ORDERS, _RELATION, _CUSTOMERS), DropTable(_ORDERS)],
        SQLiteDialect(),
    )

    assert [type(operation).__name__ for operation in plan] == ["DropTable"]


def test_a_unique_constraint_becomes_a_unique_index_where_it_has_to() -> None:
    """The same family, another surface: `ADD CONSTRAINT ... UNIQUE` does not exist in SQLite either.

    Here there is NO need to refuse, and that is why the treatment differs from the FKs: a `CREATE
    UNIQUE INDEX` gives exactly the same guarantee, and it is besides what SQLite builds underneath
    a constraint. It is translated and on we go. Refusing when there is an exact translation would
    be laziness dressed up as rigour.
    """
    unique = SnakeIndexInfo(columns=("customer_id",), unique=True)

    assert unique.is_constraint, (
        "the ORM DECLARES it as a constraint; it is the engine that cannot"
    )
    sqlite = emit_create_index(_ORDERS, unique, SQLiteDialect())
    postgres = emit_create_index(_ORDERS, unique, PostgresDialect())

    assert sqlite.startswith("CREATE UNIQUE INDEX")
    assert postgres.startswith("ALTER TABLE"), (
        "the control: on Postgres it is still a constraint"
    )


def test_dropping_that_unique_uses_the_same_shape_it_was_created_with() -> None:
    """The reverse has to match the creation or the migration back blows up.

    It is the classic failure of this emitter: it already happened once with the unnamed inline
    `UNIQUE`, which Postgres auto-named and the `DROP CONSTRAINT` then could not find.
    """
    unique = SnakeIndexInfo(columns=("customer_id",), unique=True)

    assert emit_drop_index(_ORDERS, unique, SQLiteDialect()).startswith("DROP INDEX")


def test_the_unique_index_is_actually_ENFORCED_by_the_engine() -> None:
    """And that the engine REJECT the duplicate, which is what all of this was about."""
    driver = SQLiteDriver.connect(":memory:")
    unique = SnakeIndexInfo(columns=("customer_id",), unique=True)
    try:
        driver.execute(emit_create_table(_CUSTOMERS, SQLiteDialect()), ())
        driver.execute(emit_create_table(_ORDERS, SQLiteDialect()), ())
        driver.execute(emit_create_index(_ORDERS, unique, SQLiteDialect()), ())
        driver.execute('INSERT INTO "ifk_customers" ("id") VALUES (1)', ())
        driver.execute(
            'INSERT INTO "ifk_orders" ("id", "customer_id") VALUES (1, 1)', ()
        )

        with pytest.raises(Exception, match="UNIQUE constraint failed"):
            driver.execute(
                'INSERT INTO "ifk_orders" ("id", "customer_id") VALUES (2, 1)', ()
            )
    finally:
        driver.close()


def test_the_key_is_actually_ENFORCED_by_the_engine() -> None:
    """THE proof: SQLite REJECTS an orphan row. Everything else is reading strings.

    A DDL test checks that the right SQL was written; this one checks that the database does what
    the model promised. It is the difference between the two that was needed here: the previous
    `ALTER TABLE ... ADD CONSTRAINT` generated a perfectly reasonable string SQLite did not even
    know how to parse, so referential integrity did not exist on that engine.
    """
    driver = SQLiteDriver.connect(":memory:")
    try:
        driver.execute(emit_create_table(_CUSTOMERS, SQLiteDialect()), ())
        driver.execute(emit_create_table(_ORDERS, SQLiteDialect()), ())
        driver.execute('INSERT INTO "ifk_customers" ("id") VALUES (1)', ())
        driver.execute(
            'INSERT INTO "ifk_orders" ("id", "customer_id") VALUES (1, 1)', ()
        )

        with pytest.raises(Exception, match="FOREIGN KEY constraint failed"):
            driver.execute(
                'INSERT INTO "ifk_orders" ("id", "customer_id") VALUES (2, 999)', ()
            )
    finally:
        driver.close()
