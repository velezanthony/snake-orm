"""SSR routes of the accounts domain: the role catalogue and one person's grants.

**The blueprint here is `accounts` and the JSON one next door is `accounts-api`.** Two blueprints
cannot share a `url_for` name, and the API held the plain one for as long as this domain had no pages
to collide with it — exactly the story `inventory`, `billing` and `taxonomy` already went through.

TWO ROUTES, and the absences are the domain's statement. There is no `update` and no `delete` of a
role: a role is a NAME that grants point at, so renaming one rewrites what every holder of it is
entitled to and deleting one silently strips them — the same argument `taxonomy` makes about a tag,
and the API offers neither operation either. The creation form lives ON the listing, because a role
is a name and nothing else and a whole screen for one field would be a screen for one field.

THE GRANTS PAGE IS SHAPED LIKE `taxonomy`'s, DELIBERATELY. Giving somebody a role is the same screen
as putting a tag on a post — every role in the catalogue with the held ones marked — over the same
pair of writes. ONE box per request, so `assign_role` and `revoke_role` stay visible as themselves; a
submit-everything form would collapse both into "make the rows match this list", which is a third
operation neither surface offers.

**No login**: a role is administrative and this demo has no notion of an administrator, so a gate
here would cost every reader a registration to reach a page about a bridge table. The demo gates what
has an owner.

These routes carry NO trailing slash, which is the mirror convention: Django's `APPEND_SLASH` keeps
one and Flask deliberately does not.
"""

from __future__ import annotations

from flask import Blueprint, g, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue

from apps.accounts import usecases, viewmodels
from apps.accounts.usecases import Failure

# The domain's PAGES. The JSON side is `accounts-api` in `api.py`, which is where the suffix belongs.
accounts = Blueprint("accounts", __name__, url_prefix="/accounts")

# What a refused creation says on the page that submitted it. The use case answers a reason and never
# a sentence, which is what keeps two demos from each inventing their own wording for one rule.
_ROLE_NEEDS_A_NAME = "A role needs a name."


@accounts.route("/list", methods=["GET", "POST"])
def role_directory() -> ResponseReturnValue:
    """GET: the roles and the people. POST: creates a role and comes back to the listing.

    An empty name comes back as `missing_fields` and the page is REDRAWN with the reason beside the
    form rather than redirected: a redirect would lose what the person had typed, which is the one
    thing a form must not do to somebody it has just refused.
    """
    error = ""
    if request.method == "POST":
        result = usecases.create_role(g.session, request.form.get("name", "").strip())
        if not isinstance(result, Failure):
            return redirect(url_for("accounts.role_directory"))
        error = _ROLE_NEEDS_A_NAME

    return render_template(
        "accounts/list/accounts_list.html",
        **viewmodels.role_directory(g.session, error=error),
    )


@accounts.route("/detail/<int:user_id>", methods=["GET", "POST"])
def user_roles(user_id: int) -> ResponseReturnValue:
    """GET: every role with the ones this person holds marked. POST: grants or withdraws ONE.

    A role that is not in the catalogue answers `not_found` from the use case and the page simply
    redraws: what it would show an error on is a list of the roles that DO exist, which is a better
    answer to "that role is gone" than an error page about it.
    """
    if request.method == "POST":
        raw = request.form.get("role_id", "")
        if raw.strip().isdigit():
            role_id = int(raw)
            if request.form.get("action") == "revoke":
                usecases.revoke_role(g.session, user_id, role_id)
            else:
                usecases.assign_role(g.session, user_id, role_id)
        return redirect(url_for("accounts.user_roles", user_id=user_id))

    return render_template(
        "accounts/detail/accounts_detail.html",
        **viewmodels.user_roles(g.session, user_id),
    )
