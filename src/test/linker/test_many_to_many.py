"""Many-to-many: typed navigation over a DECLARED bridge table.

The design decision is here, and it is not Django's: **the bridge is a real model that you
declare**, with its `@snake_model`, its two FKs and its table. There is no magic table showing up in
the migrations that nobody wrote.

In exchange for that extra line you get what in Django costs an explicit `through=` the day you need
it: adding a column to the bridge (when it was linked, with what role, in what order) is adding a
field to a normal model, not migrating from an implicit m2m to an explicit one.

And the m2m is NAVIGATION, not writing: linking two rows is inserting the bridge one, with `add()`,
just like any other. The ORM writes nothing you did not ask it to.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeRelationshipKind,
    SnakeToMany,
    SnakeToOne,
    snake_auto,
    snake_int,
    snake_model,
    snake_str,
    snake_to_many_through,
    snake_to_one,
)
from snakeorm.core.exceptions import SnakeUnknownRelationship
from snakeorm.linker import snake_link
from snakeorm.registry import registry


@snake_model(table="m2m_posts")
class Post(SnakeModel):
    """A post, with its tags on the other side of the bridge."""

    id: SnakeColumn[int] = snake_auto()
    titulo: SnakeColumn[str] = snake_str()
    tags: SnakeToMany["Tag"] = snake_to_many_through(
        through="PostTag", via="post", to="tag"
    )


@snake_model(table="m2m_tags")
class Tag(SnakeModel):
    """A tag, with its posts. The m2m is declared on BOTH sides if you want to navigate both ways."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    posts: SnakeToMany[Post] = snake_to_many_through(
        through="PostTag", via="tag", to="post"
    )


@snake_model(table="m2m_post_tag")
class PostTag(SnakeModel):
    """The BRIDGE: a normal model, with its table and its two foreign keys.

    It is declared after both ends because it references them. And it is a table like any other:
    the migrations create it, diff it and drop it with no special case at all.
    """

    id: SnakeColumn[int] = snake_auto()
    post_id: SnakeColumn[int] = snake_int()
    tag_id: SnakeColumn[int] = snake_int()
    post: SnakeToOne[Post] = snake_to_one(post_id)
    tag: SnakeToOne[Tag] = snake_to_one(tag_id)


def _relation(model: type, name: str) -> object:
    """The compiled relation of a model, by its name."""
    snake_link()
    table = registry.table_of(model)
    assert table is not None
    return next(rel for rel in table.relationships if rel.name == name)


def test_the_relation_is_compiled_as_many_to_many() -> None:
    """It compiles with its own `kind`: it is not a normal to-many in disguise.

    Telling them apart matters because they LOAD differently —one needs a JOIN against the bridge—
    and confusing them would produce a select-in against a table that lacks the FK being looked for.
    """
    relation = _relation(Post, "tags")

    assert relation.kind is SnakeRelationshipKind.TO_MANY_THROUGH  # type: ignore[attr-defined]
    assert relation.target == "Tag"  # type: ignore[attr-defined]


def test_a_prefetch_of_a_through_relation_keeps_its_kind() -> None:
    """Checks that `SnakePrefetch(Post.tags)` keeps the THROUGH kind and does not flatten it to TO_MANY.

    The bug: `_hop_from_collection` hardcoded `TO_MANY`, so the prefetch of an m2m got routed to the
    direct select-in planner —which looks for `post_id` in `Tag`, which does not exist— and blew
    up with a confusing `SnakeUnknownColumn` instead of going to `plan_through_level`.
    """
    from snakeorm import SnakePrefetch

    snake_link()
    prefetch = SnakePrefetch(Post.tags)
    hop = prefetch.hops()[0]
    assert hop.kind is SnakeRelationshipKind.TO_MANY_THROUGH


def test_it_carries_both_hops_of_the_bridge() -> None:
    """The metadata carries BOTH hops already resolved: bridge→parent and bridge→target.

    Resolved in the LINKER, not looked up at query time: it is the lesson of bug #14 applied from
    the start — whoever has the classes in front of them is who must store the answer.
    """
    bridge = _relation(Post, "tags").through  # type: ignore[attr-defined]

    assert bridge is not None
    assert bridge.table == "public.m2m_post_tag"
    assert bridge.to_parent == (("post_id", "id"),)
    assert bridge.to_target == (("tag_id", "id"),)


def test_the_bridge_is_a_normal_table_for_migrations() -> None:
    """The bridge shows up in the schema like any table: nothing magic that nobody declared."""
    from snakeorm.migration.autodetect import current_schema

    names = [table.name for table in current_schema(registry)]

    assert "m2m_post_tag" in names


def test_navigating_the_other_way_works_too() -> None:
    """The m2m is declared on each side you want to navigate; there is no "main" one."""
    bridge = _relation(Tag, "posts").through  # type: ignore[attr-defined]

    assert bridge is not None
    assert bridge.to_parent == (("tag_id", "id"),)
    assert bridge.to_target == (("post_id", "id"),)


def test_an_unknown_hop_is_refused_with_the_options() -> None:
    """If `via` or `to` are not relations of the bridge, it says WHICH ones are.

    A misspelled name is the most likely error of this API, and a message that limits itself to
    saying "does not exist" forces you to go and look at the model. Listing them saves that trip.
    """
    from test.linker.m2m_bad import reg

    with pytest.raises(SnakeUnknownRelationship, match="no_existe") as error:
        snake_link(reg)

    assert "a, b" in str(error.value), (
        "the message has to list the relationships that DO exist"
    )
