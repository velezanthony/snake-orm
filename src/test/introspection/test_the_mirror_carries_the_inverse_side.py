"""A foreign key has TWO ends, and the mirror was only writing one of them.

Measured against the hand-written models: 42 `snake_to_many` there, zero in the generated file. It
is not a nicety. The shared query layer reaches for the collection 17 times and none of them can be
written without it — `Plan.subscriptions.count()`, `Blog.posts.any(Post.published == True)`,
`~User.subscriptions.any()`, `Invoice.payments.sum_(...)`. An aggregate over children has no other
spelling.

The LINK costs nothing: `snake_to_many` takes the name of the child's to-one, and the generator is
the one that chose that name. What has no source in the catalogue is what the collection is called
on the parent.

THE RULE IS THE CHILD TABLE'S NAME, AS IT STANDS. It is the same kind of rule as the CapWords
already in place — mechanical, and it knows no language. It is emphatically NOT the pluraliser that
was rejected: copying a name TRANSCRIBES a token the database already holds, while pluralising
INVENTS one, and `status` → `Statu` is a wrong name that compiles and that nothing detects.
`login_sessions` where a person wrote `sessions` is not wrong, it is unabbreviated, and you can
check it against the catalogue whenever you like.

And the rule is TOTAL: every to-one has exactly one child table, so a name always exists. There is
no "not in my list" branch — which is precisely what made the deleted blacklists fail open. Its
failures are collisions, all of them decidable by looking at a single class body, and all of them
reported rather than emitted.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator

import pytest

from snakeorm.introspection.models import render_models, unrepresentable
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipInfo,
    SnakeRelationshipKind,
    SnakeTableInfo,
)
from snakeorm.registry import registry

_ID = SnakeColumnInfo(name="id", python_type=int, attr_name="id")


def _to_one(target: str, *pairs: tuple[str, str]) -> SnakeRelationshipInfo:
    """A foreign key exactly as the introspector hands it over."""
    return SnakeRelationshipInfo(
        name=target,
        target=target,
        kind=SnakeRelationshipKind.TO_ONE,
        foreign_key=SnakeForeignKeyInfo(target=target, pairs=pairs),
    )


def _table(
    name: str,
    *columns: SnakeColumnInfo,
    relationships: tuple[SnakeRelationshipInfo, ...] = (),
) -> SnakeTableInfo:
    """A table with an `id` primary key."""
    return SnakeTableInfo(
        name=name,
        columns=(_ID, *columns),
        primary_key=SnakePrimaryKeyInfo(columns=(_ID,)),
        relationships=relationships,
    )


def _column(name: str) -> SnakeColumnInfo:
    """A plain NOT NULL integer column."""
    return SnakeColumnInfo(name=name, python_type=int, attr_name=name)


def _foundries_and_lorries() -> list[SnakeTableInfo]:
    """The makers/trucks pair of the vocabulary note, renamed: the FK lives in the child."""
    return [
        _table("foundries"),
        _table(
            "lorries",
            _column("foundry_id"),
            relationships=(_to_one("foundries", ("foundry_id", "id")),),
        ),
    ]


def test_a_foreign_key_gives_the_parent_a_collection() -> None:
    """The other end of the same key, on the class that does not hold it."""
    rendered = render_models(_foundries_and_lorries())

    assert (
        '    lorries: SnakeToMany[PublicLorries] = snake_to_many("foundry")' in rendered
    )


def test_the_collection_names_the_to_one_the_generator_itself_wrote() -> None:
    """`snake_to_many` takes the CHILD's relation name, and the generator chose it.

    So the two ends cannot drift: `foundry_id` strips to `foundry` in one place and is quoted in the
    other from the same call.
    """
    rendered = render_models(_foundries_and_lorries())

    assert "foundry: SnakeToOne[PublicFoundries] = snake_to_one(foundry_id)" in rendered
    assert 'snake_to_many("foundry")' in rendered


def test_the_collection_is_the_child_table_unabbreviated() -> None:
    """`login_sessions` stays `login_sessions`. A person would write `sessions`; that is a guess.

    Transcribing is the whole rule. The moment it starts shortening it is inventing tokens the
    database does not contain, which is the pluraliser wearing a different hat.
    """
    tables = [
        _table("users"),
        _table(
            "login_sessions",
            _column("user_id"),
            relationships=(_to_one("users", ("user_id", "id")),),
        ),
    ]

    assert "login_sessions: SnakeToMany[PublicLoginSessions]" in render_models(tables)


def test_a_collection_that_would_replace_a_column_is_reported_and_left_out() -> None:
    """A parent with a column called like the child table: the attribute can only be one thing.

    Emitting it would silently REPLACE the column, and the mirror would come back short — the
    exact failure the `__` mangling used to produce.
    """
    tables = [
        _table("foundries", _column("lorries")),
        _table(
            "lorries",
            _column("foundry_id"),
            relationships=(_to_one("foundries", ("foundry_id", "id")),),
        ),
    ]

    rendered = render_models(tables)

    assert "snake_to_many" not in rendered
    assert any("already a column" in complaint for complaint in unrepresentable(tables))


def test_two_keys_from_the_same_child_leave_no_collection() -> None:
    """`sender_id` and `recipient_id` both point at `users`: ONE name for TWO collections.

    Nothing in the catalogue breaks the tie — `sent`, `inbox` and `received` are all tokens the
    database does not hold — so both are left out and both are named.
    """
    tables = [
        _table("users"),
        _table(
            "messages",
            _column("sender_id"),
            _column("recipient_id"),
            relationships=(
                _to_one("users", ("sender_id", "id")),
                _to_one("users", ("recipient_id", "id")),
            ),
        ),
    ]

    rendered = render_models(tables)

    assert "snake_to_many" not in rendered
    assert any("two foreign keys" in complaint for complaint in unrepresentable(tables))


def test_a_to_one_that_was_skipped_leaves_no_collection() -> None:
    """The reason the "is this to-one written?" test had to become ONE function.

    Here the child's relation would be called `foundry`, already a column of `lorries`, so
    the to-one is left out. A collection naming it would point at a relation nobody declared and
    `snake_link()` would die on import — a broken file produced by two rules disagreeing.
    """
    tables = [
        _table("foundries"),
        _table(
            "lorries",
            _column("foundry_id"),
            _column("foundry"),
            relationships=(_to_one("foundries", ("foundry_id", "id")),),
        ),
    ]

    rendered = render_models(tables)

    assert "snake_to_one" not in rendered
    assert "snake_to_many" not in rendered


def test_a_table_that_points_at_itself_gets_its_collection() -> None:
    """A tree: `parent_id` on the same table. Parent and child are one class, and that is fine."""
    tables = [
        _table(
            "categories",
            SnakeColumnInfo(
                name="parent_id", python_type=int, attr_name="parent_id", nullable=True
            ),
            relationships=(_to_one("categories", ("parent_id", "id")),),
        )
    ]

    rendered = render_models(tables)

    assert "parent: SnakeToOne[PublicCategories | None]" in rendered
    assert (
        'categories: SnakeToMany[PublicCategories] = snake_to_many("parent")'
        in rendered
    )


def test_a_mirror_with_no_relationships_leaves_no_dead_import() -> None:
    """Ruff runs over the generated file, and an unused `SnakeToMany` is an error there."""
    assert "SnakeToMany" not in render_models([_table("foundries")])


@pytest.fixture(scope="module")
def linked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[object]:
    """Writes the mirror, IMPORTS it and LINKS it for real."""
    dest = tmp_path_factory.mktemp("mirror_inverse")
    (dest / "mirror_inverse.py").write_text(
        render_models(_foundries_and_lorries()), encoding="utf-8"
    )
    sys.path.insert(0, str(dest))
    try:
        yield importlib.import_module("mirror_inverse")
    finally:
        sys.path.remove(str(dest))


def test_the_collection_survives_the_link(linked: object) -> None:
    """`snake_link()` resolves it, which is the only proof the two ends agree.

    A `snake_to_many` naming a relation the child does not have parses perfectly and dies here.
    """
    compiled = registry.table_of(getattr(linked, "PublicFoundries"))

    assert compiled is not None
    assert [
        relationship.name
        for relationship in compiled.relationships
        if relationship.kind is SnakeRelationshipKind.TO_MANY
    ] == ["lorries"]
