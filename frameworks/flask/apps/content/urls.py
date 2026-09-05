"""SSR routes of the content domain: the posts, and one post's history and attached files.

**The blueprint here is `content` and the JSON one next door is `content-api`.** Two blueprints
cannot share a `url_for` name, and the API held the plain one for as long as this domain had no pages
to collide with it — exactly the story `inventory`, `billing` and `taxonomy` already went through.

TWO ROUTES. A revision and an attachment do not exist apart from the post that carries them, so
neither gets a listing or a form of its own: the sheet of one post is where both are read and where
all three writes are submitted.

THE DETAIL PAGE DRAWS THE SAME TABLE TWICE ON PURPOSE, and it is the only screen in these demos that
does. The timeline is a `defer()` — every column of a revision except the one that is the size of an
article — and the panel underneath is the full read. Two questions, not one read at two widths: how
often this has been rewritten, and what it said. On a post edited two hundred times the first costs
two hundred instants and the second two hundred copies of the article, and this is the one place a
reader can see the difference rather than be told about it.

A REFUSED FORM IS REDRAWN AND NEVER REDIRECTED: an empty body or a file with no name comes back as
`missing_fields` and the page is rendered again with the reason on it, because a redirect would throw
away what the person had typed.

**No login**: a revision and an attachment belong to the POST, and the post already has an owner the
blog's own editor gates. A second gate here would cost every reader a registration to reach a page
about how a `defer()` reads.

These routes carry NO trailing slash, which is the mirror convention: Django's `APPEND_SLASH` keeps
one and Flask deliberately does not.
"""

from __future__ import annotations

from flask import Blueprint, g, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue

from apps.content import usecases, viewmodels
from apps.content.usecases import Failure

# The domain's PAGES. The JSON side is `content-api` in `api.py`, which is where the suffix belongs.
content = Blueprint("content", __name__, url_prefix="/content")

# What each refusal says on the page that submitted it. The use cases answer a reason and never a
# sentence, which is what lets two demos word a rule differently without disagreeing about the rule.
_REFUSALS: dict[str, str] = {
    "missing_fields": "A revision needs a body, and a file needs a name and a URL.",
    "not_found": "That attachment is not on this post any more.",
}


def _not_found() -> tuple[str, int]:
    """The 404 page, worded for this domain and pointing back at this domain's listing."""
    return render_template(
        "layout/error.html",
        title="Post not found",
        message="There is no post with that reference.",
        back_href=url_for("content.post_index"),
        back_label="Back to the posts",
    ), 404


def _refusal(result: object) -> str:
    """The sentence a refused write is redrawn with, or an empty string when it went through.

    It takes an `object` because the three writes answer three different shapes and only one thing
    about them matters here: whether it is a `Failure`. Widening the parameter is what keeps the
    three branches below one line each instead of each carrying its own `isinstance`.
    """
    return _REFUSALS[result.reason] if isinstance(result, Failure) else ""


def _size_bytes() -> int:
    """The declared size of an attachment. Anything unreadable is zero rather than a `ValueError`.

    A form field is whatever somebody typed into it, and a demo about revisions should not answer a
    stack trace because a size arrived as `big`. Zero is a size this domain accepts, so nothing here
    has to decide what an unparseable one means.
    """
    raw = request.form.get("size_bytes", "")
    return int(raw) if raw.strip().isdigit() else 0


def _apply(post_id: int) -> str:
    """Runs the write the form asked for and returns the message to redraw with, or an empty string.

    A helper rather than three branches inside the route, because the route's decision — redraw with
    a reason, or redirect — is the same one whichever of the three writes was submitted.
    """
    action = request.form.get("action", "")
    if action == "attach":
        return _refusal(
            usecases.attach_file(
                g.session,
                post_id,
                request.form.get("filename", "").strip(),
                request.form.get("url", "").strip(),
                _size_bytes(),
            )
        )
    if action == "remove":
        raw = request.form.get("attachment_id", "")
        if not raw.strip().isdigit():
            return _REFUSALS["not_found"]
        return _refusal(usecases.remove_attachment(g.session, int(raw)))
    return _refusal(
        usecases.add_revision(g.session, post_id, request.form.get("body", "").strip())
    )


@content.get("/list")
def post_index() -> ResponseReturnValue:
    """Every post, so a reader can open the history of one. ONE statement, authors already joined."""
    return render_template(
        "content/list/content_list.html", **viewmodels.post_index(g.session)
    )


@content.route("/detail/<int:post_id>", methods=["GET", "POST"])
def post_content(post_id: int) -> ResponseReturnValue:
    """GET: the timeline, the revisions and the attachments. POST: adds or withdraws one of them."""
    error = ""
    if request.method == "POST":
        error = _apply(post_id)
        if not error:
            return redirect(url_for("content.post_content", post_id=post_id))

    page = viewmodels.post_content(g.session, post_id, error=error)
    if isinstance(page, Failure):
        return _not_found()
    return render_template("content/detail/content_detail.html", **page)
