"""The lab's asynchronous page: use-case results turned into the rows a table paints.

A VIEWMODEL and deliberately not a use case, which took two nets to get right and both were correct.
Under `shared/aio/lab_usecases.py` it declared the lab a TWINNED DOMAIN, and `test_async_mirror`
demanded an asynchronous copy of all eight lab use cases — the very duplication
`fastapi/apps/deps.py` already argued against. Renamed out of that suffix it stopped being a twin and
started being invisible: `test_the_page_and_the_api_reach_one_usecase` walks from a route through
`apps.` and `shared.viewmodels.` only, so a module outside both is where the trail goes cold.

Here it is neither. This layer is exactly what this code does — take what a use case answered and
shape it for a page — and it is on the path the reader follows.

It composes rather than copies: every read below is an EXISTING asynchronous use case, the one the
FastAPI demo already serves. And that is the honest demonstration, because nobody wrote async
versions of these queries. `comments_of(post_id)` comes from the SYNCHRONOUS selectors untouched: a
`SnakeQuery` neither executes nor knows who will, so there is one object and not two that drift.
"""

from __future__ import annotations

from typing import Any

from snakeorm import AsyncSession, SnakeQuery, count

from shared.aio import engagement_usecases
from shared.models import Comment, Post, User

Section = dict[str, Any]


def _section(
    title: str, note: str, columns: list[str], rows: list[list[Any]]
) -> Section:
    """Packs a section, the same shape the synchronous lab uses."""
    return {"title": title, "note": note, "columns": columns, "rows": rows}


async def async_sections(session: AsyncSession, *, post_id: int = 1) -> list[Section]:
    """Three reads on the asynchronous seam, two of them straight from the async twin."""
    volumes = [
        [model.__name__, (await session.select(SnakeQuery(model), count()))[0][0]]
        for model in (User, Post, Comment)
    ]
    comments = await engagement_usecases.comments_of_post(session, post_id)
    plan = await engagement_usecases.plan_for_visits_of_post(session, post_id)
    return [
        _section(
            "Counted over an AsyncSession · one await per table",
            "Three COUNT(*) awaited in turn, on a connection borrowed from the pool and given back "
            "when the page is done with it.",
            ["table", "rows"],
            volumes,
        ),
        _section(
            f"Comments of post {post_id} · aio.engagement_usecases.comments_of_post",
            "The use case the FastAPI demo serves, called from here. ONE statement with its JOIN — "
            "the `include(Comment.author)` is the same object the synchronous page runs.",
            ["id", "author", "body"],
            [
                [comment.id, comment.author.username, comment.body[:60]]
                for comment in comments
            ],
        ),
        _section(
            "And a plan · await session.explain(...)",
            "`EXPLAIN` on the asynchronous seam. Same colourless query, same plan as the sync page.",
            ["step"],
            [[line] for line in plan],
        ),
    ]
