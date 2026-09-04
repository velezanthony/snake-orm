"""THIN SSR views of the engagement domain: the traffic board, one post's sheet and the export.

Django is a dumb shell here, the same as it is for the blog, inventory, orders, billing, taxonomy and
logistics. A view parses the request, calls ONE function of its own layer — a view model from
`apps.engagement.viewmodels`, or a use case when it writes — and turns the answer into a response. It
never touches a selector, never the session, and never walks a relation.

**THE SHEET IS THE PAGE THIS DOMAIN EXISTS FOR**, and it is where the counter kept by a TRIGGER
becomes visible. Recording a visit is the one operation in the demos whose result nothing in Python
is in a position to work out: `Post.visit_count` is moved by the engine, underneath the object the
handler is holding, so what comes back from the use case is a `refresh`ed row and not an increment.
The page prints that number.

**THE SHEET TAKES A POST**, which is where the page taxonomy bends the way `taxonomy` and `logistics`
already bent it: a browser `<form>` emits only GET and POST, so the three writes ride in the body
under an `action` rather than being three verbs on a resource the way the API spells them.

**A COMMENT AND A REACTION HAVE AN OWNER; A VISIT HAS NOT.** So the first two are gated on a signed
session and the third is not — a visit is an address and an instant, which is precisely why the API
half of it takes an `ip` rather than a user. That is the demo's rule applied, not an exception to it:
this section gates what has an owner and leaves alone what has none.

**THE EXPORT IS NOT A PAGE.** It answers with a `StreamingHttpResponse` whose body is produced after
the view has returned, so it opens a session of its own instead of borrowing the request's;
`apps/exports.py` argues the whole of it.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps import exports
from apps.blog.guards import current_user
from apps.engagement import usecases, viewmodels
from apps.engagement.usecases import Failure
from apps.session import snake_session

_session = snake_session


def _not_found(request: HttpRequest) -> HttpResponse:
    """The 404 page, worded for this domain and pointing back at this domain's board."""
    return render(
        request,
        "layout/error.html",
        {
            "user": current_user(request),
            "title": "Post not found",
            "message": "There is no post with that reference.",
            "back_href": reverse("engagement_list"),
            "back_label": "Back to the traffic board",
        },
        status=404,
    )


def _optional_post_id(request: HttpRequest) -> int | None:
    """The `?post=` of the export, as an id. Anything unreadable means "the whole log".

    The query string is hand-editable, so `post=all` is an export of everything rather than a
    `ValueError` on a route that has a perfectly good unfiltered answer to fall back to.
    """
    raw = request.GET.get("post", "")
    return int(raw) if raw.strip().isdigit() else None


def traffic_board(request: HttpRequest) -> HttpResponse:
    """Every post with the visits the trigger has counted for it. ONE statement, authors joined.

    The counter is a column on the post, so the board costs the same one query whatever the size of
    the visits table — which is the entire reason the column is denormalised and the entire reason a
    trigger keeps it.
    """
    return render(
        request,
        "engagement/list/engagement_list.html",
        {**viewmodels.traffic_board(_session(request)), "user": current_user(request)},
    )


def engagement_sheet(request: HttpRequest, post_id: int) -> HttpResponse:
    """GET: one post's comments, reactions and visits. POST: writes one of the three, then redraws.

    The POST comes back through the same shape as the GET, which is what makes the visit button
    honest: what a person sees afterwards is the counter as the DATABASE now has it, on the same row
    as the visit they just recorded. Redirecting would be a second round trip to answer a question
    that has just been answered.
    """
    session = _session(request)
    user = current_user(request)
    if request.method != "POST":
        page = viewmodels.engagement_sheet(session, post_id)
        if isinstance(page, Failure):
            return _not_found(request)
        return render(
            request, "engagement/detail/engagement_detail.html", {**page, "user": user}
        )

    action = request.POST.get("action", "")
    if action == "visit":
        page = viewmodels.record_visit(
            session, post_id, request.META.get("REMOTE_ADDR", "0.0.0.0")
        )
        if isinstance(page, Failure):
            return _not_found(request)
        return render(
            request, "engagement/detail/engagement_detail.html", {**page, "user": user}
        )

    if user is None:
        return redirect("login")
    if action == "reaction":
        usecases.add_reaction(
            session, post_id, user.id, request.POST.get("kind", "").strip()
        )
    else:
        usecases.add_comment(
            session, post_id, user.id, request.POST.get("body", "").strip()
        )
    return redirect(reverse("engagement_detail", args=[post_id]))


def visits_export(request: HttpRequest) -> StreamingHttpResponse:
    """The traffic log as a STREAMED CSV: one statement, narrow rows, flat memory.

    Not a page and not a JSON document: a file, offered from the section the domain now has. It used
    to be reachable from `/api/` only, and the reason written beside it was that this domain had no
    SSR section to hang it off — never that an export belongs on the JSON side.

    THE SESSION IS NOT THE REQUEST'S, and `apps/exports.py` argues why: the middleware closes
    `request.snake_session` the moment this function returns, and a streamed body is produced
    afterwards. `csv_download` opens one that lives exactly as long as the download.

    IT IS A PLAIN DJANGO VIEW AND NOT AN `@api_view`, so what arrives is an `HttpRequest` and the
    query string is `request.GET`. `?post=` narrows the QUERY and not the writer.
    """
    post_id = _optional_post_id(request)
    return exports.csv_download(
        lambda session: viewmodels.visits_export(session, post_id=post_id)
    )
