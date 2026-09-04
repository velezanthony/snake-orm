"""AUTH views (SSR): the login, registration and logout PAGES, and the access ledger.

They used to live on the blog's views, which is where they did not belong: the URLs already said
`/auth/*` and the JSON side already had its own `apps/auth/`, so the only thing still calling this
"blog" was the module. A domain that the route and the template agree on and the code does not is a
map with one road drawn wrong.

**AND UNTIL THE LEDGER, THE MOVE WAS THE ONLY THING THAT HAD HAPPENED.** The three views below the
forms call `usecases.login` and `usecases.register` — on the BLOG's shim, and defined in
`shared/usecases/blog_usecases.py` — so read by package this domain looked like one with pages, and
followed to the definition it had never had a screen at all. The auth domain proper is API tokens and
login sessions, and `access` is its first. `test_the_page_and_the_api_reach_one_usecase.py` is the net
that could see the difference, because it joins on the module that holds the `def`.

**THE LEDGER READS AND DOES NOT MINT.** Issuing a token and revoking one stay on the JSON surface,
which is a decision this repository already argued and two catalogues already quote: a token is for a
client with no cookie jar and a browser gets a signed session. A page that can be read is not a mint.

The session and the logged-in user come from `SnakeSessionMiddleware` and `apps.blog.guards`, which
are app-wide and run whatever view serves the request.
"""

from __future__ import annotations

import sqlite3

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render


from apps.session import snake_session
from apps.auth import viewmodels
from apps.blog import usecases
from apps.blog.guards import current_user

_INTEGRITY_ERRORS: tuple[type[Exception], ...] = (sqlite3.IntegrityError,)
try:  # psycopg2 is only there when the demo runs on Postgres.
    import psycopg2

    _INTEGRITY_ERRORS = (*_INTEGRITY_ERRORS, psycopg2.errors.UniqueViolation)
except ImportError:  # pragma: no cover - sqlite-only environment
    pass


_session = snake_session


def register(request: HttpRequest) -> HttpResponse:
    """GET: the sign-up form. POST: delegates to the `register` use case (unique username/email)."""
    if request.session.get("user_id") is not None:
        return redirect("post_list")
    if request.method != "POST":
        return render(request, "auth/register/auth_register.html", {})

    session = _session(request)
    username = (request.POST.get("username") or "").strip()
    email = (request.POST.get("email") or "").strip()
    password = request.POST.get("password") or ""

    try:
        result = usecases.register(session, username, email, password)
    except _INTEGRITY_ERRORS:
        # The DB's UNIQUE is the final net (a duplicate email / a race with another sign-up). It is
        # rolled back here because catching the exception stops the middleware's rollback-on-exception.
        session.rollback()
        return render(
            request,
            "auth/register/auth_register.html",
            {
                "error": "That email is already registered.",
                "username": username,
                "email": email,
            },
        )

    if isinstance(result, usecases.Failure):
        error = {
            "missing_fields": "Fill in user, email and password.",
            "taken": "That username is already taken.",
        }[result.reason]
        return render(
            request,
            "auth/register/auth_register.html",
            {"error": error, "username": username, "email": email},
        )
    # The use case already committed. They can log in now.
    return redirect("login")


def login(request: HttpRequest) -> HttpResponse:
    """GET: the sign-in form. POST: delegates to the `login` use case and stores `user_id` in session."""
    if request.session.get("user_id") is not None:
        return redirect("post_list")
    if request.method != "POST":
        return render(request, "auth/login/auth_login.html", {})

    session = _session(request)
    username = (request.POST.get("username") or "").strip()
    password = request.POST.get("password") or ""

    result = usecases.login(session, username, password)
    if isinstance(result, usecases.Failure):  # bad_credentials
        return render(
            request,
            "auth/login/auth_login.html",
            {"error": "Wrong user or password.", "username": username},
        )

    request.session["user_id"] = result.id
    return redirect("post_list")


def logout(request: HttpRequest) -> HttpResponse:
    """POST: clears the session (deleting the signed cookie) and goes back to the login."""
    request.session.flush()
    return redirect("login")


def access(request: HttpRequest, user_id: int) -> HttpResponse:
    """One person's API tokens and open login sessions. THREE statements, none of them per row.

    THE FIRST PAGE THIS DOMAIN HAS EVER HAD, and it is a read. The two writes it could carry —
    minting a token and revoking one — are declared to the JSON surface with an argument written down
    before this page existed, and nothing here reverses it.

    Which tokens are still standing is asked of the ENGINE and not worked out here: `active_tokens`
    is a query of its own and the ledger only marks the rows it already holds with what came back.
    The page prints both figures side by side, which is the only way the difference between the two
    reads is visible to a reader.

    IT SAYS "NOT REVOKED" AND NOT "STILL VALID", and the wording is load-bearing: that query filters
    on `revoked` and has never looked at `expires_at`, though its own docstring used to claim it did.
    `shared/viewmodels/auth_viewmodels.py` argues the gap and `shared/usecases/auth_usecases.py`
    records it where a reader will look.
    """
    return render(
        request,
        "auth/access/auth_access.html",
        {
            **viewmodels.access_ledger(_session(request), user_id),
            "user": current_user(request),
        },
    )
