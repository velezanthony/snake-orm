"""SSR routes of the taxonomy domain: FIVE pages over the one N—N and the tag TREE.

**The blueprint here is `taxonomy` and the JSON one next door is now `taxonomy-api`.** Two blueprints
cannot share a `url_for` name, and the API held the plain one for as long as this domain had no pages
to collide with it — exactly the story `inventory` and `billing` already went through. The convention
they settled is the one applied here: a plain name is the pages, the `-api` suffix is the JSON.

FOUR AND NOT SIX. There is no page to rename a tag and none to delete one, and that is the domain's
statement rather than two forms nobody wrote: a tag is a NAME that rows point at, so renaming one
rewrites the meaning of every post already carrying it, and deleting one silently unfiles them.
`shared/web/nav.py` says so in the catalogue, so the four pages cannot quietly become six.

THE FILTER IS THE PAGE THE DOMAIN EXISTS FOR. Ticking two tags asks the engine to `INTERSECT` —
requiring both is a condition on two DIFFERENT bridge rows, so no `WHERE` expresses it — and naming
one to exclude asks it to `EXCEPT`. Its opening state, nothing ticked, is neither a result nor an
error: the view model hands back a page with `asked` false and the form is drawn either way.

THE DETAIL PAGE TAKES A POST, and it is the one place here where the page taxonomy bends. A browser
`<form>` emits only GET and POST, so ticking a box is a POST to the page that shows the boxes rather
than a `POST`/`DELETE` on a tag resource the way the API does it. The action rides in the body.

**No login**: a tag has no owner — it is the vocabulary of the whole blog — so a gate here would cost
every reader a registration to reach the page they came for while testing nothing about the ORM. The
demo gates what has an owner.

These routes carry NO trailing slash, which is the mirror convention: Django's `APPEND_SLASH` keeps
one and Flask deliberately does not.
"""

from __future__ import annotations

from flask import Blueprint, g, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue

from apps.taxonomy import usecases, viewmodels
from apps.taxonomy.usecases import Failure

# The domain's PAGES. The JSON side is `taxonomy-api` in `api.py`, which is where the suffix belongs.
taxonomy = Blueprint("taxonomy", __name__, url_prefix="/taxonomy")


def _not_found() -> tuple[str, int]:
    """The 404 page, worded for this domain and pointing back at this domain's listing."""
    return render_template(
        "layout/error.html",
        title="Tag not found",
        message="That tag or post is not in the catalogue.",
        back_href=url_for("taxonomy.tag_list"),
        back_label="Back to the tags",
    ), 404


def _picked_tags() -> list[int]:
    """The ticked boxes, as ids. A box with a word in it is not a tag, so it is dropped.

    The query string is hand-editable, so `tags=orm` is a filter that names nothing rather than a
    `ValueError` on a page that has a perfectly good empty state to fall back to.
    """
    picked: list[int] = []
    for raw in request.args.getlist("tags"):
        for piece in raw.split(","):
            if piece.strip().isdigit():
                picked.append(int(piece))
    return picked


def _optional_int(name: str) -> int | None:
    """One optional integer out of the query string; anything unreadable means "not given"."""
    raw = request.args.get(name, "")
    return int(raw) if raw.strip().isdigit() else None


@taxonomy.get("/list")
def tag_list() -> ResponseReturnValue:
    """Every group with its tags. TWO statements, and neither grows with the number of groups.

    The grouping happens in the view model, over tags that arrived with their group already joined.
    Walking `group.tags` in the template would be this same page at one query per group — an N+1
    inside the renderer, which is the layer no `assert_queries` watches.
    """
    return render_template(
        "taxonomy/list/taxonomy_list.html", **viewmodels.tag_list(g.session)
    )


@taxonomy.route("/create", methods=["GET", "POST"])
def tag_create() -> ResponseReturnValue:
    """GET: the empty form. POST: creates the tag inside its group and goes back to the listing.

    An empty name comes back as `missing_fields`, and the form is REDRAWN with the reason beside it
    rather than redirected: a redirect would lose what the person had typed, which is the one thing
    a form must not do to somebody it has just refused.
    """
    if request.method == "GET":
        return render_template(
            "taxonomy/create/taxonomy_create.html", **viewmodels.tag_form(g.session)
        )

    group_raw = request.form.get("group_id", "")
    if not group_raw.strip().isdigit():
        return render_template(
            "taxonomy/create/taxonomy_create.html",
            **viewmodels.tag_form(g.session, error="Pick a group for the tag."),
        )

    parent_raw = request.form.get("parent_id", "")
    result = usecases.create_tag(
        g.session,
        request.form.get("name", ""),
        int(group_raw),
        int(parent_raw) if parent_raw.strip().isdigit() else None,
    )
    if isinstance(result, Failure):
        return render_template(
            "taxonomy/create/taxonomy_create.html",
            **viewmodels.tag_form(g.session, error="A tag needs a name."),
        )
    return redirect(url_for("taxonomy.tag_list"))


@taxonomy.route("/detail/<int:post_id>", methods=["GET", "POST"])
def post_tags(post_id: int) -> ResponseReturnValue:
    """GET: the tick boxes of one post. POST: ticks or unticks ONE of them, then redraws.

    One box per request and not a whole form, and that is what makes the two writes visible as
    themselves: `tag` calls the idempotent `get_or_create` and `untag` the `exists` + `delete_where`
    pair. A submit-everything form would collapse both into "make the row match this list", which is
    a third operation neither surface offers.
    """
    if request.method == "POST":
        tag_raw = request.form.get("tag_id", "")
        if not tag_raw.strip().isdigit():
            return _not_found()
        tag_id = int(tag_raw)
        if request.form.get("action") == "untag":
            if isinstance(usecases.untag_post(g.session, post_id, tag_id), Failure):
                return _not_found()
        else:
            usecases.tag_post(g.session, post_id, tag_id)
        return redirect(url_for("taxonomy.post_tags", post_id=post_id))

    return render_template(
        "taxonomy/detail/taxonomy_detail.html",
        **viewmodels.post_tags(g.session, post_id),
    )


@taxonomy.get("/filter")
def filter_posts() -> ResponseReturnValue:
    """The tag filter: `INTERSECT` for the ticked tags, `EXCEPT` when one is named to exclude.

    With nothing ticked the engine is asked NOTHING and the page says so. That is the screen's first
    state rather than a failure, so there is no `Failure` branch in this view at all.
    """
    page = viewmodels.filtered_posts(
        g.session, tag_ids=_picked_tags(), without=_optional_int("without")
    )
    return render_template("taxonomy/filter/taxonomy_filter.html", **page)


@taxonomy.get("/tree/<int:tag_id>")
def tag_tree(tag_id: int) -> ResponseReturnValue:
    """Where a tag sits in the taxonomy: the breadcrumb up to the root, the section underneath.

    TWO statements and neither grows with the depth of the tree. The mirror of Django's page, over
    the same view model and the same pair of recursions — a `SnakeRecursive` has no colour and no
    framework, so the two demos cannot draw two different trees out of one database.
    """
    page = viewmodels.tag_tree(g.session, tag_id)
    if isinstance(page, Failure):
        return _not_found()
    return render_template("taxonomy/tree/taxonomy_tree.html", **page)
