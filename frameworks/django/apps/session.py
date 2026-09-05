"""The request's SnakeORM session, read once and typed once.

`SnakeSessionMiddleware` opens a session per request and hangs it on `request.snake_session`. That is
a Django idiom and it works, but it is invisible to a type-checker: `HttpRequest` has no such
attribute and neither does DRF's `Request`, so every reader had to write the same line —

    return request.snake_session  # type: ignore[attr-defined]

— and it appeared SEVENTEEN times across the views and endpoints of this demo. Seventeen bare
ignores are not seventeen small concessions; they are one unchecked fact repeated, and each copy is a
place where a typo in the attribute name would have raised `AttributeError` at request time with the
checker perfectly happy.

Here the fact is stated once, and it is checked rather than asserted: the attribute is read
defensively and `isinstance` proves it is a session before it is returned. A request that reached a
view without the middleware fails by name, saying which middleware is missing, instead of crashing
three frames later on `session.query`.
"""

from __future__ import annotations

from django.http import HttpRequest
from rest_framework.request import Request

from snakeorm import SnakeSession


def snake_session(request: HttpRequest | Request) -> SnakeSession:
    """The SnakeORM session opened for this request by `SnakeSessionMiddleware`."""
    session = getattr(request, "snake_session", None)
    if not isinstance(session, SnakeSession):
        raise RuntimeError(
            "the request has no SnakeORM session: "
            "'apps.blog.middleware.SnakeSessionMiddleware' is not in MIDDLEWARE"
        )
    return session
