"""SSR routes of the blog domain: a Flask `Blueprint` with auth (register/login/logout) and CRUD.

The JSON API (with native OpenAPI/Swagger) lives apart in `api.py` (flask-smorest); here, SSR only.

The views are THIN: no queries, no rules and no inline `commit`. Each one parses the request, calls
the use case (`apps.blog.usecases`) with FLAT PARAMETERS -it never passes `request`- and translates
the result into its response: data follows the normal flow (render/redirect/JSON); a `Failure` is
mapped by its `reason` (`missing_fields`/`taken`/`bad_credentials` -> flash + redirect back to the
form; `not_found` -> 404; `forbidden` -> 403). The use case validates, orchestrates and COMMITS; the
view is only the skin.

The lifecycle of the ORM session (one per request) and the logged-in user are resolved in the
`before_app_request`/`teardown_app_request` hooks; `current_user` is injected into every template.

Two things the templates no longer say about themselves, because a template that needs a paragraph
is a template carrying logic. `create` and `update` are two PAGES because they are two operations
—different URL, different verb, different button— but their fields are ONE thing, which is why
`blog/_form.html` exists. And the listing's `.table-wrap` takes `tabindex="0"` because the wrapper
SCROLLS: a scrollable box that cannot take focus cannot be scrolled with a keyboard at all, and this
one caps at 70vh; the role and the label are what make that focus stop mean something out loud.
"""

from __future__ import annotations

import functools
from collections.abc import Callable

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.typing import ResponseReturnValue

from snakeorm import SnakeSession

from apps.blog import selectors, usecases
from apps.accounts.models import User

ViewFunc = Callable[..., ResponseReturnValue]

# The domain's Blueprint: it groups EVERY blog route (SSR + API) under its `blog` namespace.
blog = Blueprint("blog", __name__)

# The `reason` of a resource `Failure` to its HTTP code. BOTH are 404, and the pair is kept instead
# of a single constant so that the decision stays visible: a 403 on somebody else's post confirms
# that the post EXISTS, which is a fact the asker had no right to. Answering 404 to both tells them
# only what they already knew — that they cannot see it — and the page says as much.
#
# Django was already doing this ("forbidden / does not exist -> hidden as a 404"); Flask was not, so
# the same request got two different answers depending on which demo served it.
_STATUS_BY_REASON = {"not_found": 404, "forbidden": 404}


def _render_failure(failure: usecases.Failure) -> tuple[str, int]:
    """Translate a resource `Failure` (`not_found`/`forbidden`) into the error page, always a 404."""
    return render_template("layout/error.html"), _STATUS_BY_REASON[failure.reason]


# ---- Lifecycle of the ORM session and of the logged-in user (app-wide) -------------------------


def _current_user() -> User | None:
    """The logged-in user (or `None`): reads `user_id` from the signed cookie and resolves it via selector."""
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return None
    return selectors.get_user(g.session, user_id)


@blog.before_app_request
def _open_session() -> None:
    """Open the request's ORM session and resolve the logged-in user exactly once."""
    g.session = current_app.config[
        "snakeorm"
    ].open()  # ▶ SnakeORM: open from the root config
    g.current_user = _current_user()


@blog.teardown_app_request
def _close_session(_exc: BaseException | None) -> None:
    """Close the request's session (it hands the connection back to the engine)."""
    db_session: SnakeSession | None = g.pop("session", None)
    if db_session is not None:
        db_session.close()


@blog.app_context_processor
def _inject_user() -> dict[str, object]:
    """Make `current_user` available in every template (nav, edit permissions)."""
    return {"current_user": g.get("current_user")}


# ---- Auth / permissions ------------------------------------------------------------------------


def login_required(view: ViewFunc) -> ViewFunc:
    """Gate a view behind the login: with no session, it redirects to `/auth/login`."""

    @functools.wraps(view)
    def wrapped(*args: object, **kwargs: object) -> ResponseReturnValue:
        if g.get("current_user") is None:
            flash("Sign in to continue.", "warn")
            return redirect(url_for("auth.login_form", next=request.path))
        return view(*args, **kwargs)

    return wrapped


# ---- Post CRUD (SSR, behind the login) --------------------------------------------------------


@blog.get("/")
def index() -> ResponseReturnValue:
    """Root: to the listing if there is a session, otherwise to the login."""
    if g.current_user is None:
        return redirect(url_for("auth.login_form"))
    return redirect(url_for("blog.list_posts"))


@blog.get("/posts")
@login_required
def list_posts() -> ResponseReturnValue:
    """List EVERY post with its author loaded (`include` -> one single query, no N+1)."""
    posts = usecases.list_posts(g.session)
    return render_template("blog/list/blog_list.html", posts=posts)


@blog.get("/posts/<int:post_id>")
@login_required
def post_detail(post_id: int) -> ResponseReturnValue:
    """Detail of a post by id, with its author loaded. 404 if it does not exist."""
    post = usecases.show_post(g.session, post_id)
    if isinstance(post, usecases.Failure):
        return _render_failure(post)
    return render_template("blog/detail/blog_detail.html", post=post)


@blog.get("/posts/new")
@login_required
def new_post_form() -> ResponseReturnValue:
    """Post creation form."""
    return render_template("blog/create/blog_create.html")


@blog.post("/posts/new")
@login_required
def create_post() -> ResponseReturnValue:
    """Create a post authored by the logged-in user (the `create_post` use case)."""
    result = usecases.create_post(
        g.session,
        g.current_user.id,
        title=request.form.get("title", "").strip(),
        body=request.form.get("body", "").strip(),
        published=request.form.get("published") == "on",
    )
    if isinstance(result, usecases.Failure):
        flash("The title is required.", "error")
        return redirect(url_for("blog.new_post_form"))
    flash("Post created.", "ok")
    return redirect(url_for("blog.post_detail", post_id=result.id))


@blog.get("/posts/<int:post_id>/edit")
@login_required
def edit_post_form(post_id: int) -> ResponseReturnValue:
    """Edit form. Only the post's author can open it (otherwise, 403)."""
    post = usecases.editable_post(g.session, post_id, g.current_user.id)
    if isinstance(post, usecases.Failure):
        return _render_failure(post)
    return render_template("blog/update/blog_update.html", post=post)


@blog.post("/posts/<int:post_id>/edit")
@login_required
def update_post(post_id: int) -> ResponseReturnValue:
    """Update one of your own posts (the `edit_post` use case validates ownership). 403 if it is not yours."""
    result = usecases.edit_post(
        g.session,
        post_id,
        g.current_user.id,
        title=request.form.get("title", "").strip(),
        body=request.form.get("body", "").strip(),
        published=request.form.get("published") == "on",
    )
    if isinstance(result, usecases.Failure):
        return _render_failure(result)
    flash("Post updated.", "ok")
    return redirect(url_for("blog.post_detail", post_id=result.id))


@blog.get("/posts/<int:post_id>/delete")
@login_required
def confirm_delete_post(post_id: int) -> ResponseReturnValue:
    """The delete confirmation page. Only the post's author can open it (otherwise, 403).

    A destructive action reached by a link needs a stop in between: a GET must not delete anything,
    and a bare link that did would be one crawler away from emptying the blog.
    """
    post = usecases.editable_post(g.session, post_id, g.current_user.id)
    if isinstance(post, usecases.Failure):
        return _render_failure(post)
    return render_template("blog/delete/blog_delete.html", post=post)


@blog.post("/posts/<int:post_id>/delete")
@login_required
def delete_post(post_id: int) -> ResponseReturnValue:
    """Delete one of your own posts (the `remove_post` use case validates ownership). 403 if not yours."""
    failure = usecases.remove_post(g.session, post_id, g.current_user.id)
    if failure is not None:
        return _render_failure(failure)
    flash("Post deleted.", "ok")
    return redirect(url_for("blog.list_posts"))
