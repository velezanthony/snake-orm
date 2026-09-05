"""TAXONOMY domain: `TagGroup` (a group), `Tag` (a label) and the `Post` ↔ `Tag` N—N.

The N—N is EXPLICIT: `PostTag` is a REAL bridge model (with its two FKs), not an implicit magic table.
Navigation (`Post.tags` / `Tag.posts`) goes through `snake_to_many_through`; to link two rows you
insert a `PostTag` row.
"""

from __future__ import annotations

from snakeorm import (
    SnakeColumn,
    SnakeIndex,
    SnakeModel,
    SnakeToMany,
    SnakeToOne,
    snake_auto,
    snake_int,
    snake_model,
    snake_str,
    snake_to_many,
    snake_to_many_through,
    snake_to_one,
)

from shared.models.blog_models import Post


@snake_model(table="tag_groups")
class TagGroup(SnakeModel):
    """A group of tags (e.g. "temas", "lenguajes"). 1—N towards `Tag`."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(unique=True)
    tags: SnakeToMany["Tag"] = snake_to_many("group")


@snake_model(table="tags")
class Tag(SnakeModel):
    """A tag of a `TagGroup`, placed in a TREE. `Post` ↔ `Tag` is N—N through the `PostTag` bridge.

    THE TREE IS WHAT THE WORD MEANS. A taxonomy is a hierarchy — `sql` contains `orm`, which contains
    `migrations` — and a catalogue that only knows the flat list of labels cannot answer the two
    questions a reader arrives with: where am I (the breadcrumb) and what is underneath (the section).
    Both are the same walk in opposite directions, and one statement answers each.

    `parent_id` points at another row of THIS table and is nullable, which is what makes a root a
    root rather than a special case. Two levels of `include` would reach a grandparent and stop; the
    only shape that follows a chain of unknown length is `recursive()`, and the only alternative is
    one query per level — an N+1 whose depth is the data's.
    """

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(unique=True)
    group_id: SnakeColumn[int] = snake_int(index=True)
    group: SnakeToOne[TagGroup] = snake_to_one(group_id)
    # NULL means "a root of the taxonomy". The index is not decoration: every walk of the tree joins
    # the recursion onto this column, so without it each level of a `WITH RECURSIVE` scans the table.
    parent_id: SnakeColumn[int | None] = snake_int(index=True)
    parent: SnakeToOne["Tag | None"] = snake_to_one(parent_id)
    posts: SnakeToMany[Post] = snake_to_many_through(
        through="PostTag", via="tag", to="post"
    )


@snake_model(table="post_tags")
class PostTag(SnakeModel):
    """The BRIDGE of the `Post` ↔ `Tag` N—N: an ordinary model with its two FKs (no magic table).

    The pair is UNIQUE, and that index is not decoration. `tag_post` looks the link up and inserts it
    if it is not there (`get_or_create`), which is a SELECT followed by an INSERT: two transactions
    can both find nothing and both insert. The ORM says so in that method's own docstring and hands
    the problem back — uniqueness is the database's job or it is nobody's. Without this, tagging the
    same post twice from two tabs leaves two rows that mean the same thing.
    """

    id: SnakeColumn[int] = snake_auto()
    # NO `index=True` on `post_id`: the UNIQUE below already indexes `(post_id, tag_id)`, and a
    # B-tree serves any filter on a LEFTMOST PREFIX of its columns — measured on SQLite, which plans
    # `WHERE post_id = ?` as `SEARCH USING COVERING INDEX`. A second index on the same leading column
    # costs a write on every insert and buys nothing.
    #
    # `tag_id` keeps its own, and that is not an oversight: it is NOT a prefix of the composite, so
    # `WHERE tag_id = ?` — which is what `posts_for(tag)` does on every filter page — would scan.
    post_id: SnakeColumn[int] = snake_int()
    tag_id: SnakeColumn[int] = snake_int(index=True)
    post: SnakeToOne[Post] = snake_to_one(post_id)
    tag: SnakeToOne[Tag] = snake_to_one(tag_id)

    SnakeIndexes = [SnakeIndex(post_id, tag_id, unique=True)]


# The domain's models, in local dependency order for the DDL.
TAXONOMY_MODELS = (TagGroup, Tag, PostTag)
