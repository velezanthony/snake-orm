"""THIN SSR views of the taxonomy domain: the four pages of the tag graph.

Django is a dumb shell here, the same as it is for the blog, inventory, orders and billing. A view
parses the request, calls ONE function of its own layer — a view model from `apps.taxonomy.
viewmodels`, or a use case when it writes — and turns the answer into a response. It never touches a
selector, never the session, and never walks a relation.

**THE FILTER IS THE PAGE THIS DOMAIN EXISTS FOR.** Ticking two tags asks the engine to `INTERSECT`:
requiring both is a condition on two DIFFERENT bridge rows, so no `WHERE` says it. Naming one to
exclude asks it to `EXCEPT`. And its opening state — nothing ticked — is neither a result nor an
error, which is why the view model hands back a page with `asked` set to false instead of a
`Failure`. A view that turned that into a 400 would put an error page in front of a form nobody has
filled in yet.

**THE DETAIL PAGE IS WHY TAGGING HAD TO BECOME IDEMPOTENT.** It is a screen of tick boxes over one
post, and a screen of tick boxes gets submitted twice: with the old blind `add`, the second submit
left two bridge rows saying one thing. `tag_post` answers "already there" now, so re-submitting an
unchanged form changes nothing and says so.

**No login.** A tag has no owner — it is the vocabulary of the whole blog — so a gate here would cost
every reader of the demo a registration to reach the page they came for while testing nothing about
the ORM. The demo gates what has an owner, which is the call `inventory`, `orders` and `billing` all
made before this one.

`not_found` from the detail becomes `layout/error.html` with a 404, worded for this domain: the
shell's error page takes its text from the context precisely so a 404 in tags does not tell the
reader an invoice is missing.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse


from apps.session import snake_session
from apps.blog.guards import current_user
from apps.taxonomy import usecases, viewmodels
from apps.taxonomy.usecases import Failure


_session = snake_session


def _not_found(request: HttpRequest) -> HttpResponse:
    """The 404 page, worded for this domain and pointing back at this domain's listing."""
    return render(
        request,
        "layout/error.html",
        {
            "user": current_user(request),
            "title": "Tag not found",
            "message": "That tag or post is not in the catalogue.",
            "back_href": reverse("taxonomy_list"),
            "back_label": "Back to the tags",
        },
        status=404,
    )


def _picked_tags(request: HttpRequest) -> list[int]:
    """The ticked boxes, as ids. A box with a word in it is not a tag, so it is dropped.

    The query string is hand-editable, so `tags=orm` is a filter that names nothing rather than a
    `ValueError` on a page that has a perfectly good empty state to fall back to.
    """
    picked: list[int] = []
    for raw in request.GET.getlist("tags"):
        for piece in raw.split(","):
            if piece.strip().isdigit():
                picked.append(int(piece))
    return picked


def _optional_posted_int(request: HttpRequest, name: str) -> int | None:
    """One optional integer out of a submitted FORM; anything unreadable means "not given".

    The empty option of a `<select>` posts an empty string, which is how "no parent" reaches here —
    a root, and the ordinary case rather than a refusal.
    """
    raw = request.POST.get(name, "")
    return int(raw) if raw.strip().isdigit() else None


def _optional_int(request: HttpRequest, name: str) -> int | None:
    """One optional integer out of the query string; anything unreadable means "not given"."""
    raw = request.GET.get(name, "")
    return int(raw) if raw.strip().isdigit() else None


def tag_list(request: HttpRequest) -> HttpResponse:
    """Every group with its tags. TWO statements, and neither grows with the number of groups.

    The grouping happens in the view model, in one pass over tags that arrived with their group
    already loaded. Walking `group.tags` in the template would be the same page at one query per
    group — the N+1 this layer exists to keep out of the renderer.
    """
    return render(
        request,
        "taxonomy/list/taxonomy_list.html",
        {**viewmodels.tag_list(_session(request)), "user": current_user(request)},
    )


def tag_create(request: HttpRequest) -> HttpResponse:
    """GET: the empty form. POST: creates the tag inside its group and goes back to the listing.

    An empty name comes back as `missing_fields`, and the form is REDRAWN with the reason beside it
    rather than redirected: a redirect would lose what the person had typed, which is the one thing
    a form must not do to somebody it has just refused.
    """
    session = _session(request)
    user = current_user(request)
    if request.method != "POST":
        return render(
            request,
            "taxonomy/create/taxonomy_create.html",
            {**viewmodels.tag_form(session), "user": user},
        )

    group_raw = request.POST.get("group_id", "")
    if not group_raw.strip().isdigit():
        return render(
            request,
            "taxonomy/create/taxonomy_create.html",
            {
                **viewmodels.tag_form(session, error="Pick a group for the tag."),
                "user": user,
            },
        )

    result = usecases.create_tag(
        session,
        request.POST.get("name", ""),
        int(group_raw),
        _optional_posted_int(request, "parent_id"),
    )
    if isinstance(result, Failure):
        return render(
            request,
            "taxonomy/create/taxonomy_create.html",
            {
                **viewmodels.tag_form(session, error="A tag needs a name."),
                "user": user,
            },
        )
    return redirect(reverse("taxonomy_list"))


def post_tags(request: HttpRequest, post_id: int) -> HttpResponse:
    """GET: the tick boxes of one post. POST: ticks or unticks ONE of them, then redraws.

    One box per request and not a whole form, and that is what makes the two writes visible as
    themselves: `tag` calls the idempotent `get_or_create` and `untag` the `exists` + `delete_where`
    pair. A submit-everything form would collapse both into "make the row match this list", which is
    a third operation neither surface offers.
    """
    session = _session(request)
    user = current_user(request)
    if request.method == "POST":
        tag_raw = request.POST.get("tag_id", "")
        if not tag_raw.strip().isdigit():
            return _not_found(request)
        tag_id = int(tag_raw)
        if request.POST.get("action") == "untag":
            if isinstance(usecases.untag_post(session, post_id, tag_id), Failure):
                return _not_found(request)
        else:
            usecases.tag_post(session, post_id, tag_id)
        return redirect(reverse("taxonomy_detail", args=[post_id]))

    return render(
        request,
        "taxonomy/detail/taxonomy_detail.html",
        {**viewmodels.post_tags(session, post_id), "user": user},
    )


def filter_posts(request: HttpRequest) -> HttpResponse:
    """The tag filter: `INTERSECT` for the ticked tags, `EXCEPT` when one is named to exclude.

    With nothing ticked the engine is asked NOTHING and the page says so. That is the screen's first
    state rather than a failure, so there is no `Failure` branch in this view at all.
    """
    page = viewmodels.filtered_posts(
        _session(request),
        tag_ids=_picked_tags(request),
        without=_optional_int(request, "without"),
    )
    return render(
        request,
        "taxonomy/filter/taxonomy_filter.html",
        {**page, "user": current_user(request)},
    )


def tag_tree(request: HttpRequest, tag_id: int) -> HttpResponse:
    """Where a tag sits in the taxonomy: the breadcrumb up to the root, the section underneath.

    TWO statements and neither grows with the depth of the tree, which is the whole reason the
    column exists. The same page drawn without a recursion is one query per level, twice over — and
    the level count is the data's, so it is an N+1 nobody can bound from here.

    `not_found` becomes this domain's 404: a tag that is not in the catalogue has no path, and the
    recursion that would have found the path is the one that says so.
    """
    page = viewmodels.tag_tree(_session(request), tag_id)
    if isinstance(page, Failure):
        return _not_found(request)
    return render(
        request,
        "taxonomy/tree/taxonomy_tree.html",
        {**page, "user": current_user(request)},
    )
