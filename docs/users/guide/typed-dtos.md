# Typed DTOs

An application states the shape of one response more than once: the dict a view builds, the
serializer of whatever framework is in front, the TypeScript interface on the other side. Nothing
compares them, so they drift — and the drift is silent, because each of them is valid on its own.

The DTO generator collapses that to **one declaration**. You say which model and which fields; the
CLI writes the `TypedDict` into your own file, from the compiled metadata.

```bash
uv run snakeorm dto --file blog/dto.py --sync     # write them
uv run snakeorm dto --file blog/dto.py            # check only: exits 1 if anything drifted
```

## What you write

The declaration lives inside the file's own `if TYPE_CHECKING:` block, next to the import of the
models:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from snakeorm.dto import snake_dto

    from blog.models import Author, Post

    snake_dto(Author, fields=[Author.id, Author.username], name="AuthorDto")
    snake_dto(Post, fields=[Post.id, Post.title, Post.author], name="PostCard")
```

Three things: which model, which fields, and what the class is called. The name is **required** —
it is what gets written.

## What the CLI writes

Into a marked region of that same file, and nowhere else:

```python
# snakeorm-dto: begin generated block
class AuthorDto(TypedDict):
    id: int
    username: str


class PostCard(TypedDict):
    id: int
    title: str
    author: AuthorDto
# snakeorm-dto: end generated block
```

Everything outside the two marker lines is yours and is never touched. The region is regenerated
whole on every run, which is what makes a second run have nothing to write.

## Why the declaration sits inside `if TYPE_CHECKING:`

Three properties at once, and you need all three:

| | |
| --- | --- |
| the checker validates every path | `Post.tilte` does not compile |
| nothing runs at import | the block is never executed |
| the module costs nothing to import | it does not drag in the models, or the ORM |

So the file holding your DTOs is cheap to import from a view, and the import cycle between
`models.py` and `dto.py` cannot form — the import that would close it never happens.

And the CLI **reads** that block out of the source with `ast`; it never imports the file it is about
to rewrite. What it does import is the models module that file names, because the compiled metadata
is where the types and the nullability live — so a DTO file that does not import is not this
command's problem, but a models module that raises on import still is.

## The three ways to choose fields

| you write | it means |
| --- | --- |
| `snake_dto(Post, name="X")` | every column |
| `snake_dto(Post, fields=[...], name="X")` | exactly those |
| `snake_dto(Post, exclude=[...], name="X")` | all but those |

Both switches together is an error: they are two answers to one question and they can disagree.

**Prefer `fields=` for anything that crosses the wire.** An exclusion publishes every column added
later — which is the direction that fails open.

## Relationships nest, they do not expand

`Post.author` becomes `author: AuthorDto`, not the author's columns spliced in. You read `author`
and you know it is nested, and its shape is another declaration with a name of its own.

A column across a to-one is written as the path and named after it:

```python
snake_dto(Post, fields=[Post.id, Post.author.username], name="PostLine")
```

gives `author_username: str`. The whole path is in the name on purpose: with only the last step,
`author.username` and `editor.username` would both be `username` and one would quietly shadow the
other.

If a model has more than one declaration, say which one to nest:

```python
snake_dto(Post, fields=[Post.id, (Post.author, "AuthorCard")], name="PostCard")
```

Nothing is picked for you. Two declarations over one model and no rule to choose between them would
produce a valid-looking class describing the wrong shape.

## Nullability is accumulated over the whole path

`Post.editor.username` is `str | None` even though `username` is NOT NULL, because a LEFT JOIN over
a nullable `editor_id` genuinely returns nothing. `Post.editor` is `AuthorDto | None` for exactly
the same reason.

A collection is never optional: `Post.comments` is `list[CommentDto]`, because a parent with no
children gets an empty list.

## This writes the shape and never the query

Nothing here emits the `include(...)` that fills a nested relationship, and that is deliberate: an
`include()` written into your file would be a second place stating what the declaration already
states. What happens if you forget is the ORM's oldest promise rather than a hole:

```text
SnakeRelationshipNotLoaded: Relation 'author' was not loaded.
Use .include(Post.author) in the query.
```

So a declaration that nests `Post.author` describes a row read with `include(Post.author)`. Keep the
pair, and the ORM tells you when you do not.

**One way that shout can be swallowed.** `SnakeRelationshipNotLoaded` is an `AttributeError`, so
`hasattr(row, name)` answers `False` and `getattr(row, name, None)` hands back the default — both in
silence. A serializer walking a shape is written with exactly that call, because the names come from
data. Use the two-argument `getattr`, which is what the ORM does internally.

## The check mode is the point

```text
$ snakeorm dto --file blog/dto.py
blog/dto.py: Would write 1 change(s).
  AuthorDto: added `country_id: int | None`
Run `snakeorm dto --sync` to write them, and read the diff: these classes live in your files.
```

Exit code 1. Add a column to the model and the build goes red, instead of the column being published
without anyone deciding to. That is the half that makes `exclude=` and "every column" safe to use at
all.

## What it will not do

- **Write your imports.** Not even `TypedDict`. Editing somebody's import block on a guess is a
  bigger claim on their file than filling a region they marked out, and getting it wrong means the
  file stops importing. It tells you which line to add.
- **Rename a field.** `author_username` is mechanical.
- **Expand a relationship** into the far model's columns.
- **Aggregate anything.** A `COUNT` is not a shape, it is a query.

That last group is why this fits an API payload —which is the model's shape— and not a template's
row, which renames keys, flattens `None` to `""` and formats dates. Those are presentation, not
serialization.

## It is not exported from the root package

Import from `snakeorm.dto`. This is a young tool and the root package is a published surface with a
documentation net around it.

---

Next: [how typing works](../reference/typing.md).
