"""DTOs for the blog domain (user and post), SHARED by the API of the three frameworks.

That way the blog serializes THE SAME on Flask, FastAPI and Django (API parity). The `password_hash`
is NEVER exposed; the author is nested only if it was loaded (so the descriptor's N+1 lock does not
trip).

THE SHAPES ARE DECLARED, NOT TYPED OUT. The `TypedDict`s below the marker are written by
`snakeorm dto --sync` from the specs in the `if TYPE_CHECKING:` block, so what goes over the wire is
derived from the model instead of being re-stated beside it. Add a column to `Post` and the tool
says so; drop one and the checker points at every reader.

TWO SHAPES FOR ONE MODEL, and that is not duplication. `post_dict` is called both ways —
`post_dict(post)` from the taxonomy endpoints and `post_dict(post, author=...)` where the author was
included — so the payload genuinely differs. A single total `TypedDict` cannot say "this key is here
sometimes", and pretending otherwise would put the lie in the type rather than in the code. Declaring
both makes the fork visible at the call site, which is where it already lives.

Run after touching the models:

    uv run snakeorm dto --file frameworks/shared/dto/blog_dto.py --sync
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from shared.models import Post, User

if TYPE_CHECKING:
    from snakeorm.dto import snake_dto

    # `fields=` and not `exclude=[User.password_hash]`: an exclusion publishes every column added
    # later, and this shape crosses the wire. Naming what goes out is the half that fails closed.
    snake_dto(User, fields=[User.id, User.username, User.email], name="UserDto")
    snake_dto(
        Post,
        fields=[
            Post.id,
            Post.title,
            Post.body,
            Post.published,
            Post.author_id,
            # The counter the TRIGGER keeps, and the one figure on a post that nothing outside the
            # database is in a position to work out. It is a plain column, so it is already on the
            # row this function was handed — and leaving it out was what stopped a JSON client from
            # drawing the traffic board that `engagement_viewmodels.traffic_board` builds from this
            # very read. The alternative is a visit count per post, which is the N+1 over the demo's
            # biggest table that the denormalised column exists to prevent.
            Post.visit_count,
        ],
        name="PostDto",
    )
    # The same post WITH its author nested. Reaching `Post.author` here requires the row to have
    # been loaded with `include(Post.author)`; if it was not, the ORM raises
    # `SnakeRelationshipNotLoaded` naming the include to add, which is why the caller passes the
    # author in rather than this module reading it.
    snake_dto(
        Post,
        fields=[
            Post.id,
            Post.title,
            Post.body,
            Post.published,
            Post.author_id,
            Post.visit_count,
            Post.author,
        ],
        name="PostWithAuthorDto",
    )


# snakeorm-dto: begin generated block — written by `snakeorm dto --sync`, edit the specs above
class UserDto(TypedDict):
    id: int
    username: str
    email: str


class PostDto(TypedDict):
    id: int
    title: str
    body: str
    published: bool
    author_id: int
    visit_count: int


class PostWithAuthorDto(TypedDict):
    id: int
    title: str
    body: str
    published: bool
    author_id: int
    visit_count: int
    author: UserDto


# snakeorm-dto: end generated block


def user_dict(user: User) -> UserDto:
    """User to dict (without the `password_hash`)."""
    return {"id": user.id, "username": user.username, "email": user.email}


def post_dict(post: Post) -> PostDto:
    """Post to dict, without the author."""
    return {
        "id": post.id,
        "title": post.title,
        "body": post.body,
        "published": post.published,
        "author_id": post.author_id,
        "visit_count": post.visit_count,
    }


def post_with_author_dict(post: Post, author: User) -> PostWithAuthorDto:
    """The same post WITH its author nested. The caller passes the author it already loaded.

    TWO functions and not one with an optional argument, and the split is what the types bought.
    While `post_dict(post, author=None)` existed, its return had to be
    `PostDto | PostWithAuthorDto` — a union no call site could narrow, so every endpoint that
    always passes an author still declared that it might not. The caller knows which of the two it
    is; the signature now says so too.

    The author arrives as an argument rather than being read off `post.author` on purpose: reading
    it here would raise `SnakeRelationshipNotLoaded` on any row the query did not `include(...)`,
    in the middle of rendering a response. Taking it as a parameter moves that decision to where
    the query was written.
    """
    return {**post_dict(post), "author": user_dict(author)}
