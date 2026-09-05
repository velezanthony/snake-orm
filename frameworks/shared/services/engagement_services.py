"""engagement domain — SERVICES: writes (comment, react, record a visit).

They take a `SnakeSession`, mutate and return the created model. The date is set by the service
(`now`): that is business logic, not a model default. Every framework re-exports them from
`apps/engagement/services.py`.
"""

from __future__ import annotations


from snakeorm import SnakeUtc, SnakeSession

from shared.models import Comment, Reaction, Visit


def add_comment(
    session: SnakeSession, post_id: int, author_id: int, body: str
) -> Comment:
    """Adds a comment from `author_id` to `post_id`."""
    return session.add(
        Comment(
            body=body,
            post_id=post_id,
            author_id=author_id,
            created_at=SnakeUtc.now(),
        )
    )


def add_reaction(
    session: SnakeSession, post_id: int, user_id: int, kind: str
) -> Reaction:
    """Records a reaction (`kind`, e.g. 'like') from `user_id` on `post_id`."""
    return session.add(
        Reaction(
            kind=kind,
            post_id=post_id,
            user_id=user_id,
            created_at=SnakeUtc.now(),
        )
    )


def record_visit(
    session: SnakeSession, post_id: int, ip: str, user_agent: str | None = None
) -> Visit:
    """Records a visit to `post_id` (for the traffic metrics)."""
    return session.add(
        Visit(
            post_id=post_id,
            ip=ip,
            user_agent=user_agent,
            visited_at=SnakeUtc.now(),
        )
    )
