"""Typed DTOs: you declare the shape, `snakeorm dto --sync` writes the TypedDicts into your file.

    if TYPE_CHECKING:
        from blog.models import Author, Post
        from snakeorm.dto import snake_dto

        snake_dto(Author, fields=[Author.id, Author.username], name="AuthorDto")
        snake_dto(Post, fields=[Post.id, Post.title, Post.author], name="PostCard")

The declaration sits inside `if TYPE_CHECKING:` because that buys three things at once: the checker
validates every path, nothing runs at import, and the module does not drag in the models. The
generator READS that block with `ast` and never executes the file it rewrites.

Four modules, one job each:

    spec.py     what a declaration may say, and the checks both routes share
    read.py     what this file says, read from source without importing it
    resolve.py  what it MEANS against the compiled graph: types, nesting, write order
    region.py   where it is written, and why nothing outside the markers is touched

It writes the SHAPE and never the query. A spec that nests `Post.author` describes a row loaded with
`include(Post.author)`; forget it and the ORM raises `SnakeRelationshipNotLoaded` naming the call.

The facade does not re-export any of this — it is a prototype. Import from `snakeorm.dto`.
See `docs/users/guide/typed-dtos.md`.
"""

from __future__ import annotations

from snakeorm.dto.read import (
    specs_in_source as specs_in_source,
)
from snakeorm.dto.region import (
    BEGIN as BEGIN,
    END as END,
    SnakeDtoChange as SnakeDtoChange,
    SnakeDtoChangeKind as SnakeDtoChangeKind,
    SnakeDtoSyncResult as SnakeDtoSyncResult,
    sync_file as sync_file,
    sync_source as sync_source,
)
from snakeorm.dto.resolve import (
    SnakeDtoField as SnakeDtoField,
    SnakeDtoShape as SnakeDtoShape,
    resolve_all as resolve_all,
)
from snakeorm.dto.spec import (
    SnakeDtoEntry as SnakeDtoEntry,
    SnakeDtoPath as SnakeDtoPath,
    SnakeDtoPick as SnakeDtoPick,
    SnakeDtoSelection as SnakeDtoSelection,
    SnakeDtoSpec as SnakeDtoSpec,
    build_spec as build_spec,
    snake_dto as snake_dto,
)
