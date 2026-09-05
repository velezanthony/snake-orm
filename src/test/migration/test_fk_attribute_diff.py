"""Diff of the ATTRIBUTES of an FK, not just of its existence.

`_diff_foreign_keys` compared relations by NAME: if it was in both states, it did nothing at
all. So changing `on_delete=NO_ACTION` to `CASCADE` —or moving the FK onto other columns— did
not generate any migration. Silence, and a database that does not do what the model says.

Changing an FK in SQL is not altering it: it is dropping it and creating it again, in that order.

WHERE THAT NOW HAPPENS. When the key is the table's ONLY change, the diff emits one `RebuildTable`
carrying both snapshots, and the drop-then-add is the pair of statements it emits on an engine that
has `ALTER TABLE ... ADD CONSTRAINT` — the same two, in the same order. The reason is SQLite, which
has no such statement and can only change a key by remaking the table: what used to be a plan that
could not be applied there is now one operation whose spelling each dialect owns. When the table
changes anything ELSE as well, the diff keeps emitting `DropForeignKey` + `AddForeignKey`, so the
ordering rule against the column drop is untouched — and it is asserted below.
"""

from __future__ import annotations

from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeFkAction,
    SnakeForeignKeyInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeTableInfo,
)
from snakeorm.dialects import PostgresDialect
from snakeorm.migration import RebuildTable, diff_schema

_PARENT_ID = SnakeColumnInfo(name="id", python_type=int)
_PARENT = SnakeTableInfo(
    name="nations",
    columns=(_PARENT_ID,),
    primary_key=SnakePrimaryKeyInfo(columns=(_PARENT_ID,)),
)


def _resolve(target: str) -> SnakeTableInfo | None:
    """Resolves the target model of the FK (what the registry does in production)."""
    return _PARENT if target == "Nation" else None


def _child(
    *,
    on_delete: SnakeFkAction = SnakeFkAction.NO_ACTION,
    on_update: SnakeFkAction = SnakeFkAction.NO_ACTION,
    pairs: tuple[tuple[str, str], ...] = (("nation_id", "id"),),
) -> SnakeTableInfo:
    """The 'makers' table with a configurable FK towards 'nations'."""
    child_id = SnakeColumnInfo(name="id", python_type=int)
    relationship = SnakeRelationshipInfo(
        name="nation",
        target="Nation",
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=SnakeForeignKeyInfo(
            target="Nation", pairs=pairs, on_delete=on_delete, on_update=on_update
        ),
    )
    return SnakeTableInfo(
        name="makers",
        columns=(child_id, SnakeColumnInfo(name="nation_id", python_type=int)),
        primary_key=SnakePrimaryKeyInfo(columns=(child_id,)),
        relationships=(relationship,),
    )


def _diff(before: SnakeTableInfo, after: SnakeTableInfo) -> list[str]:
    """Names of the operations the diff produces between two versions of the child table."""
    operations = diff_schema([_PARENT, before], [_PARENT, after], _resolve)
    return [type(op).__name__ for op in operations]


def test_changing_on_delete_recreates_the_constraint() -> None:
    """THE GAP: going from NO_ACTION to CASCADE must generate a migration, not silence."""
    assert _diff(_child(), _child(on_delete=SnakeFkAction.CASCADE)) == ["RebuildTable"]


def test_changing_on_update_recreates_the_constraint() -> None:
    """Verifies that `on_update` is watched just like `on_delete`."""
    assert _diff(_child(), _child(on_update=SnakeFkAction.CASCADE)) == ["RebuildTable"]


def test_moving_the_fk_to_other_columns_recreates_it() -> None:
    """Verifies that changing the COLUMNS of the FK is detected too."""
    moved = _child(pairs=(("country_id", "id"),))
    assert _diff(_child(), moved) == ["RebuildTable"]


def test_the_change_is_still_a_drop_and_an_add_where_the_engine_has_them() -> None:
    """Verifies the statements did not change, only which operation carries them.

    A constraint is not altered in place on any engine. That was the reason for two operations and
    it is now the reason for two statements — the drop of the old definition and the add of the new,
    in that order, which is what Postgres and MySQL take.
    """
    before = _child()
    after = _child(on_delete=SnakeFkAction.CASCADE)
    rebuild = diff_schema([_PARENT, before], [_PARENT, after], _resolve)[0]

    statements = rebuild.up_sql(PostgresDialect())
    assert statements[0].startswith('ALTER TABLE "public"."makers" DROP CONSTRAINT')
    assert "ON DELETE CASCADE" in statements[1]
    assert "ADD CONSTRAINT" in statements[1]


def test_an_unchanged_fk_produces_nothing() -> None:
    """Verifies that an identical FK converges: without this, every makemigrations would repeat it."""
    assert (
        _diff(
            _child(on_delete=SnakeFkAction.CASCADE),
            _child(on_delete=SnakeFkAction.CASCADE),
        )
        == []
    )


def test_the_before_holds_the_old_definition_and_the_after_the_new() -> None:
    """Verifies each snapshot carries its own definition: otherwise the reverse would lie.

    The property is the one this test has always had; what carries it is now the operation's two
    snapshots instead of two operations. A `RebuildTable` whose `before` held the new referential
    action would emit a `down` that re-creates the key it was supposed to undo.
    """
    before = _child()
    after = _child(on_delete=SnakeFkAction.CASCADE)
    operations = diff_schema([_PARENT, before], [_PARENT, after], _resolve)

    (rebuild,) = operations
    assert isinstance(rebuild, RebuildTable)
    assert (
        rebuild.before.relationships[0].foreign_key.on_delete is SnakeFkAction.NO_ACTION
    )
    assert rebuild.after.relationships[0].foreign_key.on_delete is SnakeFkAction.CASCADE


def test_a_foreign_key_is_dropped_BEFORE_the_column_it_constrains() -> None:
    """Dropping a to-one emits `DropForeignKey` before `DropColumn`, or the migration dies.

    Reproduced against Postgres 5434: dropping the column takes the constraint with it, so the
    `ALTER TABLE ... DROP CONSTRAINT` that came afterwards answered
    `UndefinedObject: constraint "fk_..." of relation "..." does not exist` and the whole migration
    aborted. Removing a relationship from a model — an ordinary edit — produced a migration file
    that could not be applied.

    The ordering rule was already in this file twice: indexes are dropped before the columns change
    and created after, and so are the CHECKs, both with the reason written down. The foreign keys
    were emitted in one block at the end, so they got the ADD order right and the DROP order exactly
    backwards. Same file, same lesson, one collection short — which is the shape of nearly every
    silent failure in this codebase.
    """
    kinds = [type(op).__name__ for op in _drop_the_relationship()]

    assert "DropForeignKey" in kinds and "DropColumn" in kinds, (
        f"expected both a constraint drop and a column drop; got {kinds}"
    )
    assert kinds.index("DropForeignKey") < kinds.index("DropColumn"), (
        f"the constraint must go first: {kinds}. Dropping the column first takes the constraint "
        f"with it and the DROP CONSTRAINT then fails on a constraint that no longer exists."
    )


def _drop_the_relationship() -> list[object]:
    """The operations for removing a to-one relationship and its column."""
    identifier = SnakeColumnInfo(name="id", python_type=int)
    maker = SnakeColumnInfo(name="maker_id", python_type=int, nullable=True)

    def table(
        name: str,
        columns: tuple[SnakeColumnInfo, ...],
        relationships: tuple[SnakeRelationshipInfo, ...] = (),
    ) -> SnakeTableInfo:
        return SnakeTableInfo(
            name=name,
            columns=columns,
            primary_key=SnakePrimaryKeyInfo(columns=(columns[0],)),
            relationships=relationships,
        )

    makers = table("makers", (identifier,))
    relationship = SnakeRelationshipInfo(
        name="maker",
        target="Maker",
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=SnakeForeignKeyInfo(target="Maker", pairs=(("maker_id", "id"),)),
        target_table="makers",
    )
    return list(
        diff_schema(
            [makers, table("trucks", (identifier, maker), (relationship,))],
            [makers, table("trucks", (identifier,))],
            resolve_target=lambda _: makers,
        )
    )
