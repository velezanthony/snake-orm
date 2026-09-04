"""BLOG domain: `Blog` (a publication), `Category` (a section of a blog) and `Post` (an entry).

`Post.category_id` is a NULLABLE FK (`SnakeColumn[int | None]`): a post may have no category, and the
relationship is emitted as a LEFT JOIN. `Post.created_at` is a plain `datetime` (not a server default)
because the seeder spreads it over the history; `Blog.created_at` is a server default.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeResult,
    SnakeServerDefault,
    SnakeToMany,
    SnakeToOne,
    SnakeUtc,
    snake_auto,
    snake_column,
    snake_datetimetz,
    snake_int,
    snake_model,
    snake_result,
    snake_str,
    snake_to_many,
    snake_to_many_through,
    snake_to_one,
)

from shared.models.accounts_models import User

if TYPE_CHECKING:
    # For the TYPE-CHECKER only: names from other domains used in `Post`'s INVERSE relationships.
    # At runtime they are NOT imported (circular) — they arrive through `models/__init__.py`'s injection.
    from shared.models.content_models import Attachment, PostRevision
    from shared.models.engagement_models import Comment, Reaction, Visit
    from shared.models.taxonomy_models import Tag

    # `PostTag` is named ONLY by the `through="PostTag"` string below, so nothing else in
    # this file mentions it and ruff cannot see the connection — hence the noqa. It has to be
    # here: `through=` is resolved by reading this very block, and without the import there
    # is no path to read. Passing the class instead is not an option, because a runtime
    # argument would need a runtime import, which is the cycle this block exists to avoid.
    from shared.models.taxonomy_models import PostTag  # noqa: F401


def utcnow() -> datetime:
    """Now in UTC. A module-level function (not a lambda) so it is SERIALIZABLE in migrations."""
    return SnakeUtc.now()


@snake_model(table="blogs")
class Blog(SnakeModel):
    """A blog (publication) that groups posts and categories. Owned by a `User`."""

    id: SnakeColumn[int] = snake_auto()
    title: SnakeColumn[str] = snake_str()
    slug: SnakeColumn[str] = snake_str(unique=True)
    description: SnakeColumn[str | None] = (
        snake_str()
    )  # nullable because of the annotation
    owner_id: SnakeColumn[int] = snake_int(index=True)
    owner: SnakeToOne[User] = snake_to_one(owner_id)
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )
    categories: SnakeToMany["Category"] = snake_to_many("blog")
    posts: SnakeToMany["Post"] = snake_to_many("blog")


@snake_model(table="categories")
class Category(SnakeModel):
    """A category (section) inside a `Blog` (1—N). A post may belong to one, or to none."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    slug: SnakeColumn[str] = snake_str(unique=True)
    blog_id: SnakeColumn[int] = snake_int(index=True)
    blog: SnakeToOne[Blog] = snake_to_one(blog_id)
    posts: SnakeToMany["Post"] = snake_to_many("category")


@snake_model(table="posts")
class Post(SnakeModel):
    """A post of a `Blog`, written by a `User`, with an OPTIONAL category. `created_at` is spread by the seeder."""

    id: SnakeColumn[int] = snake_auto()
    title: SnakeColumn[str] = snake_str()
    body: SnakeColumn[str] = snake_str()
    published: SnakeColumn[bool] = snake_column(default=False)
    # DENORMALISED, and kept by a TRIGGER rather than by the ORM. Counting `visits` is the honest
    # query and it is the one that does not scale: the volume table carries millions of rows, and a
    # listing of twenty posts would pay twenty COUNTs or one GROUP BY over all of them.
    #
    # The rule the ORM's own guide gives for reaching a trigger is exactly this one: if the invariant
    # has to hold ALWAYS —including for writes that never go through this ORM— it belongs in the
    # database. See `visit_counter` at the foot of `engagement_models.py`.
    visit_count: SnakeColumn[int] = snake_int(default=0)
    blog_id: SnakeColumn[int] = snake_int(index=True)
    blog: SnakeToOne[Blog] = snake_to_one(blog_id)
    category_id: SnakeColumn[int | None] = snake_int(
        index=True
    )  # nullable FK -> LEFT JOIN
    category: SnakeToOne[Category | None] = snake_to_one(category_id)
    author_id: SnakeColumn[int] = snake_int(index=True)
    author: SnakeToOne[User] = snake_to_one(author_id)
    # `default_factory` = the date AT CONSTRUCTION: the CRUD creates the post without passing it (it
    # comes out as "now"); the seeder OVERWRITES it with a date from the history. One single field,
    # both paths happy. The factory is a MODULE-LEVEL function (not a lambda): serializable in
    # migrations.
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(default_factory=utcnow)
    revisions: SnakeToMany["PostRevision"] = snake_to_many("post")
    attachments: SnakeToMany["Attachment"] = snake_to_many("post")
    comments: SnakeToMany["Comment"] = snake_to_many("post")
    visits: SnakeToMany["Visit"] = snake_to_many("post")
    reactions: SnakeToMany["Reaction"] = snake_to_many("post")
    tags: SnakeToMany["Tag"] = snake_to_many_through(
        through="PostTag", via="post", to="tag"
    )


@snake_result
class BlogStats(SnakeResult[Blog]):
    """Typed container for `session.annotate()`: the blog + its 1-hop aggregates (posts and
    categories). Traffic per blog (2 hops: blog→posts→visits) is computed separately with `group_by`."""

    blog: Blog
    post_count: int
    category_count: int


# The domain's models, in local dependency order for the DDL.
BLOG_MODELS = (Blog, Category, Post)
