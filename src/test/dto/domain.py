"""The models the DTO tests declare their shapes over.

They live in a module of their own because `@snake_model` registers on IMPORT, and two test files
declaring the same table would collide in the global registry. One declaration, imported twice.
"""

from __future__ import annotations

from datetime import datetime

from snakeorm import SnakeColumn, snake_auto, snake_model, snake_str
from snakeorm.fields import (
    SnakeToMany,
    SnakeToOne,
    snake_datetime,
    snake_int,
    snake_json,
    snake_to_many,
    snake_to_one,
)
from snakeorm.linker.linker import snake_link
from snakeorm.registry import SnakeRegistry


@snake_model(table="dto_users")
class DtoUser:
    """A user with one column nobody outside the process is allowed to read."""

    id: SnakeColumn[int] = snake_auto()
    username: SnakeColumn[str] = snake_str(max_length=50)
    email: SnakeColumn[str] = snake_str(max_length=200)
    password_hash: SnakeColumn[str] = snake_str(max_length=200)
    bio: SnakeColumn[str | None] = snake_str(max_length=500)
    created_at: SnakeColumn[datetime] = snake_datetime()


@snake_model(table="dto_settings")
class DtoSettings:
    """A model whose columns need a name the generated file does not have in scope."""

    id: SnakeColumn[int] = snake_auto()
    payload: SnakeColumn[dict] = snake_json()  # type: ignore[type-arg]
    changed_at: SnakeColumn[datetime] = snake_datetime()


class DtoPlain:
    """Not a model: nothing ever compiled it, so it has no column list to read."""


FLAT = SnakeRegistry()
"""A registry of its OWN for the models a flatten crosses.

Relationships only exist once `snake_link()` has run, and linking is per registry. Calling it over
the global one from a test module would walk every model the whole suite has imported — including
classes declared inside other tests' function bodies, where `get_type_hints` cannot resolve the
annotations. Measured: that is 304 failures in files that have nothing to do with DTOs.
"""


@snake_model(table="dto_flat_countries", registry=FLAT)
class FlatCountry:
    """The far end of a two-hop path. Its `name` is NOT NULL, which is the point of it."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(max_length=60)


@snake_model(table="dto_flat_authors", registry=FLAT)
class FlatAuthor:
    """The middle of the path: reachable through a NOT NULL key and through a nullable one."""

    id: SnakeColumn[int] = snake_auto()
    username: SnakeColumn[str] = snake_str(max_length=50)
    country_id: SnakeColumn[int | None] = snake_int()
    country: SnakeToOne[FlatCountry | None] = snake_to_one(country_id)


@snake_model(table="dto_flat_posts", registry=FLAT)
class FlatPost:
    """Two to-ones onto the same model — one required, one optional — and a to-many.

    `author` and `editor` are the pair the nullability rule is measured on: the SAME target and the
    same column at the end of the path, reached across keys that differ in exactly one way.
    """

    id: SnakeColumn[int] = snake_auto()
    title: SnakeColumn[str] = snake_str(max_length=200)
    author_id: SnakeColumn[int] = snake_int()
    editor_id: SnakeColumn[int | None] = snake_int()
    author: SnakeToOne[FlatAuthor] = snake_to_one(author_id)
    editor: SnakeToOne[FlatAuthor | None] = snake_to_one(editor_id)
    comments: SnakeToMany[FlatComment] = snake_to_many("post")


@snake_model(table="dto_flat_comments", registry=FLAT)
class FlatComment:
    """The child of the to-many, which a flatten must refuse to cross."""

    id: SnakeColumn[int] = snake_auto()
    body: SnakeColumn[str] = snake_str(max_length=500)
    post_id: SnakeColumn[int] = snake_int()
    post: SnakeToOne[FlatPost] = snake_to_one(post_id)


snake_link(FLAT)
