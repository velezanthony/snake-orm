"""A domain built to tell apart the THREE states a relationship can be in, against a real engine.

A generated DTO types those three differently, so they had better be different at runtime:

    not loaded                  ->  SnakeRelationshipNotLoaded, and no DTO shape at all
    to-one loaded, no partner   ->  None, and the DTO says `AuthorDto | None`
    to-many loaded, no children ->  [], and the DTO says `list[CommentDto]`

Collapsing any two of them would make the generator's `| None` a promise nothing backs. The seed is
shaped so all three exist at once: `LoadedPost` 1 has an editor and two comments, `LoadedPost` 2 has
neither — same query, same shapes, opposite answers.

Uncommon table names because the global registry is shared with the rest of the suite.
"""

from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.drivers import SnakeDriver
from snakeorm.fields import (
    SnakeColumn,
    SnakeToMany,
    SnakeToOne,
    snake_int,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.model import SnakeModel


@snake_model(table="dto_loaded_authors")
class LoadedAuthor(SnakeModel):
    """The far side of both to-ones: one required, one optional."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    username: SnakeColumn[str] = snake_str()


@snake_model(table="dto_loaded_posts")
class LoadedPost(SnakeModel):
    """The three shapes on one model, so one query can be asked all three questions.

    `author` and `editor` point at the SAME model through keys that differ in exactly one way, which
    is what isolates "the key was NULL" from anything else that could produce a `None`.
    """

    id: SnakeColumn[int] = snake_int(primary_key=True)
    title: SnakeColumn[str] = snake_str()
    author_id: SnakeColumn[int] = snake_int()
    editor_id: SnakeColumn[int | None] = snake_int()
    author: SnakeToOne[LoadedAuthor] = snake_to_one(author_id)
    editor: SnakeToOne[LoadedAuthor | None] = snake_to_one(editor_id)
    comments: SnakeToMany[LoadedComment] = snake_to_many("post")


@snake_model(table="dto_loaded_comments")
class LoadedComment(SnakeModel):
    """The child of the to-many. Post 2 deliberately has none."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    body: SnakeColumn[str] = snake_str()
    post_id: SnakeColumn[int] = snake_int()
    post: SnakeToOne[LoadedPost] = snake_to_one(post_id)


_DDL = (
    "DROP TABLE IF EXISTS dto_loaded_comments, dto_loaded_posts, dto_loaded_authors CASCADE",
    "CREATE TABLE dto_loaded_authors (id INTEGER PRIMARY KEY, username TEXT NOT NULL)",
    "CREATE TABLE dto_loaded_posts ("
    " id INTEGER PRIMARY KEY, title TEXT NOT NULL,"
    " author_id INTEGER NOT NULL REFERENCES dto_loaded_authors(id),"
    " editor_id INTEGER REFERENCES dto_loaded_authors(id))",
    "CREATE TABLE dto_loaded_comments ("
    " id INTEGER PRIMARY KEY, body TEXT NOT NULL,"
    " post_id INTEGER NOT NULL REFERENCES dto_loaded_posts(id))",
)


def create_schema(driver: SnakeDriver) -> None:
    """Creates (resetting) the tables of the loaded-state domain."""
    for statement in _DDL:
        driver.execute(statement, ())


def seed(driver: SnakeDriver) -> None:
    """Post 1 has an editor and two comments; post 2 has neither. Both have an author."""
    driver.execute(
        "INSERT INTO dto_loaded_authors VALUES (1, 'ada'), (2, 'grace')",
        (),
    )
    driver.execute(
        "INSERT INTO dto_loaded_posts VALUES (1, 'edited', 1, 2), (2, 'raw', 1, NULL)",
        (),
    )
    driver.execute(
        "INSERT INTO dto_loaded_comments VALUES (1, 'first', 1), (2, 'second', 1)",
        (),
    )
