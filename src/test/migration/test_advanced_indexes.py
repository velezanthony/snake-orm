"""Advanced indexes: partial ones (`where=`) and ones with a method (`method=`).

Two pieces a real project asks for straight away:

- The PARTIAL index (`WHERE deleted_at IS NULL`) is what makes soft-delete and multi-tenant
  usable. And it is the documented EXCEPTION to unifying uniqueness: Postgres does not accept
  `CONSTRAINT ... UNIQUE ... WHERE`, so a partial unique only exists as an INDEX. Without
  `where=` uniqueness is a constraint; with `where=`, an index. And it is said out loud.
- The METHOD (`GIN`, `GiST`, `BRIN`...) is declared with an AGNOSTIC enum the dialect translates,
  just like `SnakeServerDefault` and `SnakeFkAction`: the engine jargon does not enter the model.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakeIndexMethod,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.migration import (
    CreateIndex,
    diff_schema,
    emit_create_index,
    emit_drop_index,
)

_DIALECT = PostgresDialect()
_ID = SnakeColumnInfo(name="id", python_type=int)
_ALIVE = SnakeExpr[int](path=("deleted_at",)).is_null()


def _table(*indexes: SnakeIndexInfo) -> SnakeTableInfo:
    """The 'users' table with the columns of the soft-delete scenario."""
    return SnakeTableInfo(
        name="users",
        columns=(
            _ID,
            SnakeColumnInfo(name="email", python_type=str),
            SnakeColumnInfo(name="deleted_at", python_type=int, nullable=True),
        ),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        indexes=indexes,
    )


def test_a_partial_index_carries_its_where() -> None:
    """Verifies that the `where=` is emitted as `WHERE ...`, with the literals written out."""
    index = SnakeIndexInfo(columns=("email",), where=_ALIVE)
    assert emit_create_index(_table(), index, _DIALECT) == (
        'CREATE INDEX "ix_users_email" ON "public"."users" ("email") '
        'WHERE "deleted_at" IS NULL'
    )


def test_a_partial_unique_index_stays_an_index() -> None:
    """THE EXCEPTION: a PARTIAL unique cannot be a constraint, so it stays an index.

    Postgres does not accept `CONSTRAINT ... UNIQUE ... WHERE`. It is the only case where
    `unique=True` produces no `uq_*` constraint, hence the name changes to `ix_*` too: another object.
    """
    index = SnakeIndexInfo(columns=("email",), unique=True, where=_ALIVE)
    ddl = emit_create_index(_table(), index, _DIALECT)

    assert ddl == (
        'CREATE UNIQUE INDEX "ix_users_email" ON "public"."users" ("email") '
        'WHERE "deleted_at" IS NULL'
    )
    assert "CONSTRAINT" not in ddl


def test_a_partial_unique_index_is_dropped_as_an_index() -> None:
    """Verifies that the reverse of the partial unique is `DROP INDEX`, not `DROP CONSTRAINT`."""
    index = SnakeIndexInfo(columns=("email",), unique=True, where=_ALIVE)
    assert (
        emit_drop_index(_table(), index, _DIALECT)
        == 'DROP INDEX "public"."ix_users_email"'
    )


def test_a_full_unique_index_is_still_a_constraint() -> None:
    """Verifies that WITHOUT `where=` uniqueness is still a constraint (nothing got broken)."""
    index = SnakeIndexInfo(columns=("email",), unique=True)
    assert "ADD CONSTRAINT" in emit_create_index(_table(), index, _DIALECT)


def test_the_method_is_translated_by_the_dialect() -> None:
    """Verifies that the method is declared agnostic and the dialect translates it to `USING ...`."""
    index = SnakeIndexInfo(columns=("email",), method=SnakeIndexMethod.GIN)
    assert emit_create_index(_table(), index, _DIALECT) == (
        'CREATE INDEX "ix_users_email" ON "public"."users" USING GIN ("email")'
    )


def test_btree_is_the_default_and_stays_implicit() -> None:
    """Verifies that the default method does not dirty the DDL with a redundant `USING BTREE`."""
    index = SnakeIndexInfo(columns=("email",), method=SnakeIndexMethod.BTREE)
    assert "USING" not in emit_create_index(_table(), index, _DIALECT)


def test_the_diff_sees_a_changed_where() -> None:
    """Verifies that changing the condition of the partial index generates a migration (drop + create)."""
    before = SnakeIndexInfo(columns=("email",), where=_ALIVE)
    after = SnakeIndexInfo(
        columns=("email",), where=SnakeExpr[int](path=("deleted_at",)).is_not_null()
    )

    kinds = [type(op).__name__ for op in diff_schema([_table(before)], [_table(after)])]
    assert kinds == ["DropIndex", "CreateIndex"]


def test_the_diff_sees_a_changed_method() -> None:
    """Verifies that changing the method recreates the index too: SQL does not alter one in place."""
    before = SnakeIndexInfo(columns=("email",))
    after = SnakeIndexInfo(columns=("email",), method=SnakeIndexMethod.GIN)

    kinds = [type(op).__name__ for op in diff_schema([_table(before)], [_table(after)])]
    assert kinds == ["DropIndex", "CreateIndex"]


def test_an_unchanged_partial_index_converges() -> None:
    """Verifies that an identical partial index produces no operations.

    The conditions are compared by the SQL they emit, not by object identity: the AST nodes use
    `eq=False`, so two equivalent conditions are different objects.
    """
    equivalent = SnakeIndexInfo(
        columns=("email",), where=SnakeExpr[int](path=("deleted_at",)).is_null()
    )
    assert (
        diff_schema(
            [_table(SnakeIndexInfo(columns=("email",), where=_ALIVE))],
            [_table(equivalent)],
        )
        == []
    )


def test_create_index_round_trips_its_up_and_down() -> None:
    """Verifies that the operation is reversible with `where` and `method` together."""
    index = SnakeIndexInfo(
        columns=("email",), where=_ALIVE, method=SnakeIndexMethod.BRIN
    )
    operation = CreateIndex(_table(), index)

    assert "USING BRIN" in operation.up_sql(_DIALECT)[0]
    assert operation.down_sql(_DIALECT) == ['DROP INDEX "public"."ix_users_email"']
