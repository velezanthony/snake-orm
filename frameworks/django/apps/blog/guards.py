"""Session-cookie authentication: who is logged in and which views demand a login.

We do not use Django's auth system (nor its ORM): the `user_id` lives in `request.session` (a signed
cookie) and the `User` is resolved with the `get_user` SELECTOR over the request's SnakeORM session
(`request.snake_session`). The view never queries the DB directly; it delegates to
`apps.blog.selectors`.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from apps.blog import selectors
from apps.accounts.models import User
from apps.session import snake_session

View = Callable[..., HttpResponse]


def current_user(request: HttpRequest) -> User | None:
    """The logged-in `User` (per `user_id` in the session cookie), or `None` if there is no session."""
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    session = snake_session(request)
    return selectors.get_user(session, int(user_id))


def login_required(view: View) -> View:
    """Decorator: with no user in session, it redirects to `login` instead of serving the view."""

    @wraps(view)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.session.get("user_id") is None:
            return redirect("login")
        return view(request, *args, **kwargs)

    return wrapped
