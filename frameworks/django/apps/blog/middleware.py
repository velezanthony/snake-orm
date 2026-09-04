"""Middleware that opens ONE SnakeORM session per request and closes it when the request ends.

Unit-of-work contract:
- It opens `django_session()` — SnakeORM's linker reads `settings.DATABASES` (Django's NATIVE config)
  and builds the session with the driver wrapped in `CaptureDriver` (so the panel sees the SQL).
- It hangs it on `request.snake_session` so views and API can use it.
- When the request ends: **commit** if everything went fine, **rollback** if the view raised, and
  **close** always (it returns the connection).

It goes as the INNERMOST middleware, inside the capture scope opened by `SnakeDebugMiddleware`, so
all of its SQL (the commit's included) shows up in the SSR panel and in the API envelope.
"""

from __future__ import annotations

from typing import Any

from snakeorm.contrib.django import django_session


class SnakeSessionMiddleware:
    """SnakeORM session bound to the request lifecycle (automatic commit/rollback/close)."""

    def __init__(self, get_response: Any) -> None:
        self._get_response = get_response

    def __call__(self, request: Any) -> Any:
        """Opens the session, runs the view and commits or rolls back depending on whether it raised."""
        session = django_session()
        request.snake_session = session
        try:
            response = self._get_response(request)
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()
            return response
        finally:
            session.close()
