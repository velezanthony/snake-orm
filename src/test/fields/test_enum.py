"""`snake_enum`: TYPED enumeration columns, with the rule enforced by the database.

This is no Django-style `TextChoices`. Python 3.11 already ships `StrEnum` and `IntEnum`: what was
missing was not a new type, it was the ORM knowing how to store them and hand them back WITHOUT
losing the type. Here the enum travels whole: a member goes in and a member comes out, never the
raw `str`.

The `storage` decides WHICH database object backs the rule:

- `CHECK` (the default) — stored through the base type (a VARCHAR sized by the enum's longest
  member, or BIGINT) with a `CHECK col IN (...)`. It is the only
  reversible one: adding a value is a clean migration, and removing one fails during the `migrate`
  if there are rows using it, not in production.
- `PLAIN` — no validation in the DB at all. The conversion works, but nothing stops anyone from
  shoving garbage in through raw SQL, and that garbage blows up ON READING IT.
- There is no `NATIVE` (`CREATE TYPE`): studied and discarded. As far as Postgres is concerned the
  column is a string with its constraint, so the native type only bought four bytes per row in
  exchange for rewriting the table on EVERY change of the enum. The full reasoning, with what was
  measured against the engine, lives in the docstring of `SnakeEnumStorage`.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeEnumStorage,
    SnakeModel,
    snake_auto,
    snake_column,
    snake_enum,
    snake_model,
    snake_table,
)
from snakeorm.dialects import PostgresDialect
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.migration import emit_create_table


class Status(StrEnum):
    """Lifecycle status of an account."""

    ACTIVE = "active"
    BANNED = "banned"


class Priority(IntEnum):
    """Numeric priority, orderable."""

    LOW = 1
    HIGH = 10


@snake_model(table="enum_accounts")
class Account(SnakeModel):
    """Account holding a text enum, a numeric one and an optional one."""

    id: SnakeColumn[int] = snake_auto()
    status: SnakeColumn[Status] = snake_enum(Status, default=Status.ACTIVE)
    priority: SnakeColumn[Priority] = snake_enum(Priority, default=Priority.LOW)
    reason: SnakeColumn[Status | None] = snake_enum(Status)


def test_the_enum_reaches_the_metadata_graph() -> None:
    """The compiler stores the type of the enum and its storage strategy."""
    column = snake_table(Account).get_column("status")
    assert column is not None
    assert column.enum_type is Status
    assert column.enum_storage is SnakeEnumStorage.CHECK


def test_a_str_enum_is_stored_as_text_and_an_int_enum_as_integer() -> None:
    """The STORAGE type: the dialect maps the base type, never the enum itself."""
    table = snake_table(Account)
    assert table.get_column("status").storage_type is str  # type: ignore[union-attr]
    assert table.get_column("priority").storage_type is int  # type: ignore[union-attr]


def test_the_ddl_uses_the_base_type_and_adds_the_check() -> None:
    """The whole DDL: a VARCHAR sized by the enum / BIGINT, plus the CHECK listing the valid values.

    `VARCHAR(6)` and not `TEXT`: both members are six characters long, and the metadata derives that
    width from the enum itself (see `SnakeColumnInfo.__post_init__`). It is not a domain restriction
    anybody declared — it is the width the enum already implies, and MySQL needs it spelled out or
    an index over the column does not fit in InnoDB's key budget.
    """
    ddl = emit_create_table(snake_table(Account), PostgresDialect())

    assert '"status" VARCHAR(6) NOT NULL' in ddl
    # An IntEnum is stored through its `int` base, which defaults to BIGINT, the widest width.
    assert '"priority" BIGINT NOT NULL' in ddl
    assert "CHECK (\"status\" IN ('active', 'banned'))" in ddl
    assert 'CHECK ("priority" IN (1, 10))' in ddl


def test_the_nullable_enum_comes_from_the_annotation() -> None:
    """Nullability is still told by the annotation, enum or not."""
    column = snake_table(Account).get_column("reason")
    assert column is not None and column.nullable is True


def test_the_default_is_a_member_not_a_string() -> None:
    """The default value is the MEMBER of the enum, not its representation.

    `reason` is passed explicitly: being nullable does not make it optional in the constructor. It
    is the same rule as in `snake_column` —a column with no default is a required argument— and it
    is not bent here just because this happens to be an enum.
    """
    account = Account(reason=None)
    assert account.status is Status.ACTIVE
    assert account.priority is Priority.LOW


def test_a_default_that_is_not_a_member_is_rejected() -> None:
    """The guard: a default that is NOT a member of the enum is rejected at declaration, not in DDL.

    The signature types `default: E | object`, which collapses to `object`, so the checker does not
    catch it; without the runtime guard, `default=42` or `default="active"` (the raw value, not the
    member) ended up as a loose literal in the DEFAULT of the CREATE TABLE, silently.
    """
    with pytest.raises(SnakeModelDefinitionError, match="is not a member of Status"):
        snake_enum(Status, default=42)  # just any old int
    with pytest.raises(SnakeModelDefinitionError, match="is not a member of Status"):
        snake_enum(Status, default="active")  # the raw value, not Status.ACTIVE


def test_a_plain_enum_column_skips_the_check() -> None:
    """With `PLAIN` no constraint is emitted: the conversion yes, the validation no."""

    @snake_model(table="enum_plain")
    class Loose(SnakeModel):
        """Model holding an enum with no validation in the DB."""

        id: SnakeColumn[int] = snake_auto()
        status: SnakeColumn[Status] = snake_enum(Status, storage=SnakeEnumStorage.PLAIN)

    ddl = emit_create_table(snake_table(Loose), PostgresDialect())
    # Still sized by the enum: the width is derived from the members, and `storage` only decides
    # whether a DB object VALIDATES them. The two are not tangled.
    assert '"status" VARCHAR(6) NOT NULL' in ddl
    assert "CHECK" not in ddl


def test_there_are_exactly_two_storage_strategies() -> None:
    r"""Postgres's NATIVE type is NOT an option, and that is a decision, not a shortcoming.

    It was studied and it does not pay off. What a `CREATE TYPE ... AS ENUM` buys you is four bytes
    per row and a line in `\dT`. What it costs, measured against Postgres 15:

    - `ALTER TYPE ... ADD VALUE` has no inverse (there is no `DROP VALUE`), so the only reversible
      way is to RECREATE the whole type — and that rewrites the table under an `ACCESS EXCLUSIVE`
      on every change of the enum, even when all you add is one value.
    - Worse: `ADD VALUE` lets you add the value inside a transaction but NOT use it until you commit
      it (`UnsafeNewEnumValueUsage`). Migrations run inside a transaction, so one that adds a value
      and migrates data with it would blow up.

    With `CHECK` none of that exists: as far as Postgres is concerned the column is a string with
    its constraint, twenty tables can use the same Python enum without sharing anything, adding a
    value is instantaneous and removing one fails if there are rows using it. `NATIVE` is not kept
    around as a member that raises, because a declarable state that never works is dead metadata —
    the very trap `db_comment` turned out to be.
    """
    assert [member.name for member in SnakeEnumStorage] == ["CHECK", "PLAIN"]


def test_an_enum_declared_with_snake_column_fails_loudly() -> None:
    """An Enum without `snake_enum` does NOT slip through: one single path, and an explicit one.

    It used to blow up late and ugly, down in the dialect (`does not know how to map <enum> to an
    SQL type`). Now it fails while compiling the model and says exactly what to write.
    """
    with pytest.raises(SnakeModelDefinitionError, match="snake_enum"):

        @snake_model(table="enum_wrong")
        class Wrong(SnakeModel):
            """Badly declared model: the enum goes through `snake_column`."""

            id: SnakeColumn[int] = snake_auto()
            status: SnakeColumn[Status] = snake_column()


def test_an_enum_that_is_neither_text_nor_numeric_is_refused() -> None:
    """A bare `Enum` with arbitrary values is rejected, and with a useful message."""
    from enum import Enum

    class Weird(Enum):
        """Enum whose values are neither str nor int."""

        A = (1, 2)

    with pytest.raises(SnakeModelDefinitionError, match="StrEnum"):
        snake_enum(Weird)
