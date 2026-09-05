"""THIN SSR views of the accounts domain: the role catalogue and one person's grants.

Django is a dumb shell here, the same as it is for every other section. A view parses the request,
calls ONE function of its own layer — a view model from `apps.accounts.viewmodels`, or a use case
when it writes — and turns the answer into a response. It never touches a selector, never the
session, and never walks a relation.

**THE GRANTS PAGE IS SHAPED LIKE `taxonomy`'s, AND THAT IS DELIBERATE.** Giving somebody a role is
the same screen as putting a tag on a post — every role in the catalogue, with the held ones marked —
over the same pair of writes: one that adds a bridge row and one that removes it. Using the same
shape is the point of having a page taxonomy at all; inventing a third way to draw an N—N would make
two sections that do the same thing look like two different things.

**ONE BOX PER REQUEST**, exactly as `taxonomy` does it, and for the same reason: `assign_role` and
`revoke_role` stay visible as themselves. A submit-everything form would collapse both into "make
the rows match this list", which is a third operation neither surface offers.

**No login.** A role is administrative and the demo has no notion of an administrator; a gate here
would cost every reader a registration to reach a page about a bridge table. The demo gates what has
an owner, which is the call `inventory`, `orders`, `billing`, `taxonomy` and `logistics` all made
before this one.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.accounts import usecases, viewmodels
from apps.accounts.usecases import Failure
from apps.blog.guards import current_user
from apps.session import snake_session

_session = snake_session

# What a refused creation says on the page that submitted it. The use case answers a reason and never
# a sentence, which is what keeps three frameworks from each inventing their own wording.
_ROLE_NEEDS_A_NAME = "A role needs a name."


def role_directory(request: HttpRequest) -> HttpResponse:
    """GET: the roles and the people. POST: creates a role and comes back to the listing.

    An empty name comes back as `missing_fields` and the page is REDRAWN with the reason beside the
    form rather than redirected: a redirect would lose what the person had typed, which is the one
    thing a form must not do to somebody it has just refused.
    """
    session = _session(request)
    user = current_user(request)
    error = ""
    if request.method == "POST":
        result = usecases.create_role(session, request.POST.get("name", "").strip())
        if not isinstance(result, Failure):
            return redirect(reverse("accounts_list"))
        error = _ROLE_NEEDS_A_NAME

    return render(
        request,
        "accounts/list/accounts_list.html",
        {**viewmodels.role_directory(session, error=error), "user": user},
    )


def user_roles(request: HttpRequest, user_id: int) -> HttpResponse:
    """GET: every role with the ones this person holds marked. POST: grants or withdraws ONE.

    A role that is not in the catalogue answers `not_found` from the use case, and the page simply
    redraws: the screen it would show an error on is a list of the roles that DO exist, which is a
    better answer to "that role is gone" than an error page about it.
    """
    session = _session(request)
    if request.method == "POST":
        raw = request.POST.get("role_id", "")
        if raw.strip().isdigit():
            role_id = int(raw)
            if request.POST.get("action") == "revoke":
                usecases.revoke_role(session, user_id, role_id)
            else:
                usecases.assign_role(session, user_id, role_id)
        return redirect(reverse("accounts_detail", args=[user_id]))

    return render(
        request,
        "accounts/detail/accounts_detail.html",
        {
            **viewmodels.user_roles(session, user_id),
            "user": current_user(request),
        },
    )
