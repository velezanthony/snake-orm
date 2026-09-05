"""AUTH routes (SSR): the login, registration and logout PAGES, and the access ledger.

They used to live on the blog's blueprint, which is where they did not belong: the URLs already said
`/auth/*` and the JSON side already had its own `apps/auth/`, so the only thing still calling this
"blog" was the code. A domain that the route and the template agree on and the module does not is a
map with one road drawn wrong.

**AND UNTIL THE LEDGER, THE MOVE WAS THE ONLY THING THAT HAD HAPPENED.** The four routes below the
forms call `usecases.login` and `usecases.register` — on the BLOG's shim, and defined in
`shared/usecases/blog_usecases.py` — so read by package this domain looked like one with pages, while
the tokens and login sessions it is actually about had never been drawn at all. `access` is its first
real screen, and `test_the_page_and_the_api_reach_one_usecase.py` is the net that could see the
difference, because it joins on the module that holds the `def`.

**THE LEDGER READS AND DOES NOT MINT.** Issuing a token and revoking one stay on the JSON surface,
which is a decision this repository already argued and two catalogues already quote: a token is for a
client with no cookie jar and a browser gets a signed session. A page that can be read is not a mint.

The blueprint is `auth` and the JSON one is `auth-api`, which lines this domain up with `blog` /
`blog-api` and `lab` / `lab-api`: a plain name is the pages, the `-api` suffix is the JSON.

The ORM session and `g.current_user` are set up by the blog blueprint's app-wide hooks
(`before_app_request`), which run for every request whatever blueprint serves it.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.typing import ResponseReturnValue

from apps.auth import viewmodels
from apps.blog import usecases

# The auth PAGES. Everything at the root, under `/auth/*`.
auth_web = Blueprint("auth", __name__)


@auth_web.get("/auth/register")
def register_form() -> ResponseReturnValue:
    """Registration form."""
    if g.current_user is not None:
        return redirect(url_for("blog.list_posts"))
    return render_template("auth/register/auth_register.html")


@auth_web.post("/auth/register")
def register() -> ResponseReturnValue:
    """Create a new user (unique username/email, hashed password) and log them in."""
    result = usecases.register(
        g.session,
        request.form.get("username", "").strip(),
        request.form.get("email", "").strip(),
        request.form.get("password", ""),
    )
    if isinstance(result, usecases.Failure):
        message = (
            "Username, email and password are required."
            if result.reason == "missing_fields"
            else "That username or email already exists."
        )
        flash(message, "error")
        return redirect(url_for("auth.register_form"))
    session["user_id"] = result.id
    flash(f"Account created. Welcome, {result.username}!", "ok")
    return redirect(url_for("blog.list_posts"))


@auth_web.get("/auth/login")
def login_form() -> ResponseReturnValue:
    """Login form."""
    if g.current_user is not None:
        return redirect(url_for("blog.list_posts"))
    return render_template("auth/login/auth_login.html")


@auth_web.post("/auth/login")
def login() -> ResponseReturnValue:
    """Verify the credentials with the `login` use case and store `user_id` in the signed cookie."""
    result = usecases.login(
        g.session,
        request.form.get("username", "").strip(),
        request.form.get("password", ""),
    )
    if isinstance(result, usecases.Failure):
        flash("Wrong username or password.", "error")
        return redirect(url_for("auth.login_form"))
    session["user_id"] = result.id
    flash(f"Signed in as {result.username}.", "ok")
    target = request.args.get("next") or url_for("blog.list_posts")
    return redirect(target)


@auth_web.post("/auth/logout")
def logout() -> ResponseReturnValue:
    """Log out: it wipes the signed cookie entirely."""
    session.clear()
    flash("Signed out.", "ok")
    return redirect(url_for("auth.login_form"))


@auth_web.get("/auth/access/<int:user_id>")
def access(user_id: int) -> ResponseReturnValue:
    """One person's API tokens and open login sessions. THREE statements, none of them per row.

    THE FIRST PAGE THIS DOMAIN HAS EVER HAD, and it is a read. The two writes it could carry —
    minting a token and revoking one — are declared to the JSON surface with an argument written down
    before this page existed, and nothing here reverses it.

    Which tokens are still standing is asked of the ENGINE and not worked out here: `active_tokens`
    is a query of its own and the ledger only marks the rows it already holds with what came back.

    IT SAYS "NOT REVOKED" AND NOT "STILL VALID", and the wording is load-bearing: that query filters
    on `revoked` and has never looked at `expires_at`, though its own docstring used to claim it did.
    `shared/viewmodels/auth_viewmodels.py` argues the gap and `shared/usecases/auth_usecases.py`
    records it where a reader will look.
    """
    return render_template(
        "auth/access/auth_access.html", **viewmodels.access_ledger(g.session, user_id)
    )
