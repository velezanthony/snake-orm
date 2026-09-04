"""SSR routes of the engagement domain: the traffic board, one post's sheet and the export.

**The blueprint here is `engagement` and the JSON one next door is `engagement-api`.** Two blueprints
cannot share a `url_for` name, and the API held the plain one for as long as this domain had no pages
to collide with it — exactly the story `inventory`, `billing` and `taxonomy` already went through.
The convention they settled is the one applied here: a plain name is the pages, the `-api` suffix is
the JSON.

THREE ROUTES AND NOT FIVE. There is no `create` page: a comment, a reaction and a visit are written
from the sheet of the post they belong to, because none of the three exists apart from a post. And
there is no `delete`, because this demo has no operation that withdraws a comment or a reaction — the
API has none either, so a page for it would be a screen over a use case that does not exist.

THE SHEET IS THE PAGE THE DOMAIN EXISTS FOR, and it is where a TRIGGER becomes visible. Recording a
visit is the one operation in these demos whose result nothing in Python can work out: `visit_count`
is moved by the engine underneath the object the handler holds, so what comes back is a `refresh`ed
row rather than an increment, and the page prints that number.

THE SHEET TAKES A POST, which is where the page taxonomy bends the way `taxonomy` and `logistics`
already bend it: a browser `<form>` emits only GET and POST, so the three writes ride in the body
under an `action` rather than being three verbs on a resource.

A COMMENT AND A REACTION HAVE AN OWNER; A VISIT HAS NOT. So the first two are gated on the signed
session and the third is not — a visit is an address and an instant, which is why the API half takes
an `ip` and no user. That is the demo's rule applied rather than an exception to it.

These routes carry NO trailing slash, which is the mirror convention: Django's `APPEND_SLASH` keeps
one and Flask deliberately does not.
"""

from __future__ import annotations

from flask import Blueprint, g, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue

from apps.engagement import usecases, viewmodels
from apps.engagement.usecases import Failure
from apps.exports import csv_response

# The domain's PAGES. The JSON side is `engagement-api` in `api.py`, which is where the suffix
# belongs.
engagement = Blueprint("engagement", __name__, url_prefix="/engagement")


def _not_found() -> tuple[str, int]:
    """The 404 page, worded for this domain and pointing back at this domain's board."""
    return render_template(
        "layout/error.html",
        title="Post not found",
        message="There is no post with that reference.",
        back_href=url_for("engagement.traffic_board"),
        back_label="Back to the traffic board",
    ), 404


@engagement.get("/list")
def traffic_board() -> ResponseReturnValue:
    """Every post with the visits the trigger has counted for it. ONE statement, authors joined.

    The counter is a column on the post, so the board costs the same single query whatever the size
    of the visits table — which is the entire reason the column is denormalised and the entire reason
    a trigger keeps it. Counting `post.visits` per row instead would be an N+1 over the demo's
    biggest table.
    """
    return render_template(
        "engagement/list/engagement_list.html", **viewmodels.traffic_board(g.session)
    )


@engagement.route("/detail/<int:post_id>", methods=["GET", "POST"])
def engagement_sheet(post_id: int) -> ResponseReturnValue:
    """GET: one post's comments, reactions and visits. POST: writes one of the three, then redraws.

    The visit comes back through the same shape as the GET, which is what makes the button honest:
    what a person sees afterwards is the counter as the DATABASE now has it, next to the visit they
    just recorded. The comment and the reaction redirect instead, because a form that has been
    accepted should not be re-submittable by a refresh.
    """
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "visit":
            page = viewmodels.record_visit(
                g.session, post_id, request.remote_addr or "0.0.0.0"
            )
            if isinstance(page, Failure):
                return _not_found()
            return render_template("engagement/detail/engagement_detail.html", **page)
        if g.current_user is None:
            return redirect(url_for("auth.login_form"))
        if action == "reaction":
            usecases.add_reaction(
                g.session,
                post_id,
                g.current_user.id,
                request.form.get("kind", "").strip(),
            )
        else:
            usecases.add_comment(
                g.session,
                post_id,
                g.current_user.id,
                request.form.get("body", "").strip(),
            )
        return redirect(url_for("engagement.engagement_sheet", post_id=post_id))

    sheet = viewmodels.engagement_sheet(g.session, post_id)
    if isinstance(sheet, Failure):
        return _not_found()
    return render_template("engagement/detail/engagement_detail.html", **sheet)


@engagement.get("/export")
def export_visits() -> ResponseReturnValue:
    """The traffic log as a STREAMED CSV. One statement, narrow rows, and memory that does not grow.

    The generator is never touched here. `csv_response` writes the header and then pulls a row at a
    time from the cursor — and it TAKES THE SESSION WITH IT: `g.session` is popped, so the teardown
    hook has nothing to close and the stream owns the connection until the download ends. That is why
    this is the last statement of the function; nothing may touch the session afterwards.

    `?post=` narrows the QUERY and not the writer. An unknown id is still a filter the engine can
    run, so it downloads a header with no rows under it — which is what "no visits" looks like.
    """
    export = viewmodels.visits_export(
        g.session, post_id=request.args.get("post", default=None, type=int)
    )
    return csv_response(export)
