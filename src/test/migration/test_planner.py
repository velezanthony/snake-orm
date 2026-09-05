"""Tests of the application order BY FK DEPENDENCY (`dependency_order`).

The dependency is DERIVED from the FKs (`target_table`), not declared by hand: the migration that
creates a table goes BEFORE the one that references it. The TO_MANY (reverse) ones do NOT count
—the FK lives in the other table—, so they introduce no cycles.
"""

from __future__ import annotations

from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeTableInfo,
)
from snakeorm.migration import CreateTable, Migration, dependency_order


def _table(name: str, *, refs: str | None = None) -> SnakeTableInfo:
    """A table; with `refs`, a TO_ONE FK to that target table (`target_table` resolved)."""
    pk = SnakeColumnInfo(name="id", python_type=int)
    relationships: tuple[SnakeRelationshipInfo, ...] = ()
    if refs is not None:
        relationships = (
            SnakeRelationshipInfo(
                name=refs,
                target=refs.title(),
                kind=SnakeRelationshipKind.TO_ONE,
                foreign_key=SnakeForeignKeyInfo(
                    target=refs.title(), pairs=((f"{refs}_id", "id"),)
                ),
                target_table=f"public.{refs}",
            ),
        )
    return SnakeTableInfo(
        name=name,
        columns=(pk,),
        primary_key=SnakePrimaryKeyInfo(columns=(pk,)),
        relationships=relationships,
    )


def _migration(version: str, table: SnakeTableInfo) -> Migration:
    return Migration(version=version, operations=(CreateTable(table),))


def test_creator_comes_before_referencer() -> None:
    """The migration that CREATES a table goes before the one that references it, whatever the input order."""
    users = _migration("0001_accounts", _table("users"))
    posts = _migration("0001_blog", _table("posts", refs="users"))  # posts → users
    ordered = dependency_order([posts, users])  # input the other way round
    assert [m.version for m in ordered] == ["0001_accounts", "0001_blog"]


def test_reference_to_external_table_imposes_no_order() -> None:
    """An FK to a table that NO migration of the set creates (already there) imposes no order."""
    posts = _migration(
        "0001_blog", _table("posts", refs="users")
    )  # users is not in the set
    ordered = dependency_order([posts])
    assert [m.version for m in ordered] == [
        "0001_blog"
    ]  # it does not blow up, does not cycle


def test_to_many_reverse_does_not_cycle() -> None:
    """A reverse TO_MANY (the FK lives in the other table) imposes NO dependency: no cycle."""
    # `users` with a TO_MANY to posts (reverse); `posts` with TO_ONE to users. It must not cycle.
    users_table = SnakeTableInfo(
        name="users",
        columns=(SnakeColumnInfo(name="id", python_type=int),),
        primary_key=SnakePrimaryKeyInfo(
            columns=(SnakeColumnInfo(name="id", python_type=int),)
        ),
        relationships=(
            SnakeRelationshipInfo(
                name="posts",
                target="Post",
                kind=SnakeRelationshipKind.TO_MANY,
                foreign_key=SnakeForeignKeyInfo(
                    target="Post", pairs=(("id", "author_id"),)
                ),
                target_table="public.posts",
            ),
        ),
    )
    users = _migration("0001_accounts", users_table)
    posts = _migration("0001_blog", _table("posts", refs="users"))
    ordered = dependency_order(
        [posts, users]
    )  # does not raise SnakeMigrationError (cycle)
    assert [m.version for m in ordered] == ["0001_accounts", "0001_blog"]
