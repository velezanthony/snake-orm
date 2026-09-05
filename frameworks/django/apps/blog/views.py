"""THIN SSR views: registration, login/logout and post CRUD (each user manages THEIR OWN).

Django is a DUMB shell here: the view only parses the request (POST/GET), calls a USE CASE from
`apps.blog.usecases` (which re-exports `shared`) with the request's session and FLAT PARAMETERS —
never the `request` — and translates the result into a response: a value follows the normal flow
(redirect/render); a `Failure` maps to an error message plus a re-render
(`missing_fields`/`taken`/`bad_credentials`) or to `not_found.html` with a 404
(`not_found`/`forbidden`, so other people's posts are not revealed to exist).

The functionality (uniqueness, credentials, post ownership, `commit`) lives in the use case, not
here. The SnakeORM session is hung on `request.snake_session` by `SnakeSessionMiddleware`; its
end-of-request commit is left as a harmless no-op because the use case already committed. The ORM's
debug panel is injected by `SnakeDebugMiddleware` before `</body>`.

Two things the templates do without saying why, because a template says nothing — the reasons live
here, where the rest of the reasoning already is:

- `create` and `update` are two pages and ONE partial (`blog/_form.html`). Two pages because they are
  two operations, with a different URL, a different verb and a different button; one partial because
  the fields are a single thing, and a second copy of them is how the two pages start disagreeing
  about what a post has.
- the listing's table wrapper carries `tabindex="0"`, and it is not decoration: the box SCROLLS —it
  caps at 70vh— and a scrollable box that cannot take focus cannot be scrolled with a keyboard at
  all. The `role="region"` and the label are what make that focus stop mean something when a screen
  reader announces it.
"""

from __future__ import annotations

import sqlite3

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render


from apps.session import snake_session
from apps.blog import usecases
from apps.blog.guards import current_user, login_required

# Integrity errors (a UNIQUE violation) according to the active driver. The `register` use case
# validates username uniqueness, but the email's is enforced by the DB inside the service; here that
# failure is only translated into a friendly message. psycopg2 is optional (only on the Postgres
# path), so its class is added defensively.
_INTEGRITY_ERRORS: tuple[type[Exception], ...] = (sqlite3.IntegrityError,)
try:  # pragma: no cover - depends on the engine chosen in the .env
    import psycopg2

    _INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg2.IntegrityError)
except ImportError:  # pragma: no cover
    pass


_session = snake_session


# --- Autenticación ------------------------------------------------------------------------------


# --- post CRUD (gated by login; each user, their own) -------------------------------------------


@login_required
def post_list(request: HttpRequest) -> HttpResponse:
    """SSR: ALL posts with their author loaded (the `list_posts` use case -> 1 JOIN, no N+1)."""
    session = _session(request)
    user = current_user(request)
    posts = usecases.list_posts(session)
    rows = [
        {
            "id": post.id,
            "title": post.title,
            "published": post.published,
            "author": post.author.username,  # already loaded by the selector's include
            "mine": post.author_id == (user.id if user else None),
        }
        for post in posts
    ]
    return render(request, "blog/list/blog_list.html", {"posts": rows, "user": user})


@login_required
def post_detail(request: HttpRequest, post_id: int) -> HttpResponse:
    """SSR: one post by id with its author (the `show_post` use case). 404 if it does not exist."""
    session = _session(request)
    user = current_user(request)
    result = usecases.show_post(session, post_id)
    if isinstance(result, usecases.Failure):  # not_found
        return render(request, "layout/error.html", {"user": user}, status=404)
    context = {
        "post": result,
        "author": result.author.username,
        "mine": user is not None and result.author_id == user.id,
        "user": user,
    }
    return render(request, "blog/detail/blog_detail.html", context)


@login_required
def post_create(request: HttpRequest) -> HttpResponse:
    """GET: the creation form. POST: delegates to `create_post` with the logged-in user as author."""
    user = current_user(request)
    assert user is not None  # guaranteed by @login_required
    if request.method != "POST":
        return render(
            request, "blog/create/blog_create.html", {"mode": "create", "user": user}
        )

    session = _session(request)
    title = (request.POST.get("title") or "").strip()
    body = (request.POST.get("body") or "").strip()
    published = request.POST.get("published") == "on"

    result = usecases.create_post(
        session, user.id, title=title, body=body, published=published
    )
    if isinstance(result, usecases.Failure):  # missing_fields (título vacío)
        return render(
            request,
            "blog/create/blog_create.html",
            {
                "mode": "create",
                "error": "The title is required.",
                "title": title,
                "body": body,
                "published": published,
                "user": user,
            },
        )
    return redirect("post_list")


@login_required
def post_edit(request: HttpRequest, post_id: int) -> HttpResponse:
    """GET: the filled form (`editable_post`). POST: updates via `edit_post`. 404 if it is not theirs."""
    session = _session(request)
    user = current_user(request)
    assert user is not None

    if request.method != "POST":
        editable = usecases.editable_post(session, post_id, user.id)
        if isinstance(
            editable, usecases.Failure
        ):  # forbidden / does not exist -> hidden as a 404
            return render(request, "layout/error.html", {"user": user}, status=404)
        return render(
            request,
            "blog/update/blog_update.html",
            {
                "mode": "edit",
                "post_id": editable.id,
                "title": editable.title,
                "body": editable.body,
                "published": editable.published,
                "user": user,
            },
        )

    title = (request.POST.get("title") or "").strip()
    body = (request.POST.get("body") or "").strip()
    published = request.POST.get("published") == "on"
    if not title:
        return render(
            request,
            "blog/update/blog_update.html",
            {
                "mode": "edit",
                "post_id": post_id,
                "error": "The title is required.",
                "title": title,
                "body": body,
                "published": published,
                "user": user,
            },
        )
    updated = usecases.edit_post(
        session, post_id, user.id, title=title, body=body, published=published
    )
    if isinstance(updated, usecases.Failure):  # forbidden -> hidden as a 404
        return render(request, "layout/error.html", {"user": user}, status=404)
    return redirect("post_detail", post_id=post_id)


@login_required
def post_delete(request: HttpRequest, post_id: int) -> HttpResponse:
    """POST: deletes via `remove_post` (which validates ownership). GET: the confirmation page."""
    session = _session(request)
    user = current_user(request)
    assert user is not None

    if request.method == "POST":
        result = usecases.remove_post(session, post_id, user.id)
        if isinstance(
            result, usecases.Failure
        ):  # forbidden / does not exist -> hidden as a 404
            return render(request, "layout/error.html", {"user": user}, status=404)
        return redirect("post_list")

    # GET: the confirmation page (only if the post is theirs).
    editable = usecases.editable_post(session, post_id, user.id)
    if isinstance(editable, usecases.Failure):
        return render(request, "layout/error.html", {"user": user}, status=404)
    return render(
        request, "blog/delete/blog_delete.html", {"post": editable, "user": user}
    )
