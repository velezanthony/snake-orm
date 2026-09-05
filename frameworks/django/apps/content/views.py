"""THIN SSR views of the content domain: the posts, and one post's history and attached files.

Django is a dumb shell here, the same as it is for the blog, inventory, orders, billing, taxonomy and
logistics. A view parses the request, calls ONE function of its own layer — a view model from
`apps.content.viewmodels`, or a use case when it writes — and turns the answer into a response. It
never touches a selector, never the session, and never walks a relation.

**THE DETAIL PAGE DRAWS THE SAME TABLE TWICE ON PURPOSE**, and it is the only screen in the demos
that does. The timeline is a `defer()` — every column of a revision except the one that is the size
of an article — and the panel underneath is the full read. Two questions, not one read at two widths:
"how often has this been rewritten" and "what did it say". On a post edited two hundred times the
first costs two hundred instants and the second two hundred copies of the article, which is the whole
argument for the narrow query and the only place a reader can see it.

**A REFUSED FORM IS REDRAWN, NEVER REDIRECTED.** An empty body or a file with no name comes back as
`missing_fields`, and the page is rendered again with the reason on it: a redirect would throw away
what the person had typed, which is the one thing a form must not do to somebody it has just refused.

**No login.** A revision and an attachment belong to the POST, and the post already has an owner the
blog's own editor gates. A second gate here would cost every reader of the demo a registration to
reach a page about how a `defer()` reads, which tests nothing about ownership.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from snakeorm import SnakeSession

from apps.blog.guards import current_user
from apps.content import usecases, viewmodels
from apps.content.usecases import Failure
from apps.session import snake_session

_session = snake_session

# What each refusal says on the page that was submitted. The use cases answer a reason and never a
# sentence, which is what lets three frameworks and two languages of prose disagree about the wording
# without disagreeing about the rule.
_REFUSALS: dict[str, str] = {
    "missing_fields": "A revision needs a body, and a file needs a name and a URL.",
    "not_found": "That attachment is not on this post any more.",
}


def _not_found(request: HttpRequest) -> HttpResponse:
    """The 404 page, worded for this domain and pointing back at this domain's listing."""
    return render(
        request,
        "layout/error.html",
        {
            "user": current_user(request),
            "title": "Post not found",
            "message": "There is no post with that reference.",
            "back_href": reverse("content_list"),
            "back_label": "Back to the posts",
        },
        status=404,
    )


def _size_bytes(request: HttpRequest) -> int:
    """The declared size of an attachment. Anything unreadable is zero rather than a `ValueError`.

    A form field is whatever somebody typed into it, and a demo about revisions should not answer a
    stack trace because a size arrived as `big`. Zero is a size the domain accepts, so nothing here
    has to decide what an unparseable one means.
    """
    raw = request.POST.get("size_bytes", "")
    return int(raw) if raw.strip().isdigit() else 0


def post_index(request: HttpRequest) -> HttpResponse:
    """Every post, so a reader can open the history of one. ONE statement, authors already joined."""
    return render(
        request,
        "content/list/content_list.html",
        {**viewmodels.post_index(_session(request)), "user": current_user(request)},
    )


def post_content(request: HttpRequest, post_id: int) -> HttpResponse:
    """GET: the timeline, the revisions and the attachments. POST: adds or withdraws one of them."""
    session = _session(request)
    user = current_user(request)
    error = ""
    if request.method == "POST":
        error = _apply(request, session, post_id)
        if not error:
            return redirect(reverse("content_detail", args=[post_id]))

    page = viewmodels.post_content(session, post_id, error=error)
    if isinstance(page, Failure):
        return _not_found(request)
    return render(request, "content/detail/content_detail.html", {**page, "user": user})


def _refusal(result: object) -> str:
    """The sentence a refused write is redrawn with, or an empty string when it went through.

    It takes the result as an `object` because the three writes answer three different shapes and
    only one of them matters here: whether it is a `Failure`. Widening the parameter is what lets
    the three branches below stay one line each instead of each carrying its own `isinstance`.
    """
    return _REFUSALS[result.reason] if isinstance(result, Failure) else ""


def _apply(request: HttpRequest, session: SnakeSession, post_id: int) -> str:
    """Runs the write the form asked for and returns the message to redraw with, or an empty string.

    A helper rather than three branches inside the view, because the view's job is to decide between
    "redraw with a reason" and "redirect", and that decision is the same one whichever of the three
    writes was submitted. Returning the SENTENCE rather than the reason keeps `_REFUSALS` the one
    place a wording lives.
    """
    action = request.POST.get("action", "")
    if action == "attach":
        return _refusal(
            usecases.attach_file(
                session,
                post_id,
                request.POST.get("filename", "").strip(),
                request.POST.get("url", "").strip(),
                _size_bytes(request),
            )
        )
    if action == "remove":
        raw = request.POST.get("attachment_id", "")
        if not raw.strip().isdigit():
            return _REFUSALS["not_found"]
        return _refusal(usecases.remove_attachment(session, int(raw)))
    return _refusal(
        usecases.add_revision(session, post_id, request.POST.get("body", "").strip())
    )
