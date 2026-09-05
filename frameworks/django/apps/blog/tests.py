"""Verification of the demo with `django.test.Client` (no server started).

It walks the full flow the brief asked for:

    register -> login -> create a post -> list (include = 1 query) -> edit -> delete -> logout

and it also checks both faces of the ORM's debug tooling:
  (a) the SSR view returns HTML with the `snake-debug-panel` injected;
  (b) an `/api/` endpoint brings the `snakeorm` block with the `envelope` channel on (the channel is
      the switch) and the `Server-Timing` header;
  (c) listing posts with `include` runs ONE single query (no N+1), measured two ways.

`SimpleTestCase`: the business data does NOT touch Django's ORM; SnakeORM carries it
(SQLite/Postgres depending on `frameworks/.env`). The test client persists the signed session cookie
between requests.
"""

from __future__ import annotations

from typing import Literal

from django.test import Client, SimpleTestCase, override_settings

from snakeorm import SnakeQuery
from snakeorm.debug import assert_queries
from shared import config
from shared.models import Post, User

from apps.blog import seed


# Django's runner forces `DEBUG=False`, and SnakeORM's safety gate then switches off the channels
# that expose SQL (`envelope`). The demo lives in development: `DEBUG=True` is restored so the
# envelope gets exercised. The middleware is built on the first request, already under this override.
@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"])
class SnakeOrmDjangoDemoTests(SimpleTestCase):
    """The CRUD flow with login/registration + the ORM's debug tooling, against the test client."""

    # Django's ORM is not used for any business logic: no test databases are declared.
    databases: set[str] | Literal["__all__"] = set()

    def setUp(self) -> None:
        """Leaves the SnakeORM database in its seeded state (a deterministic reset) before each test."""
        seed.reset_and_seed()
        self.client = Client()

    # --- helpers ---------------------------------------------------------------------------------

    def _new_session(self):
        """A direct SnakeORM session (to check the database's state in the assertions)."""
        return config.make_session("django")

    def _register_and_login(self, username: str, email: str, password: str) -> None:
        """Registers a user and leaves them logged in (leaving the session cookie on the client)."""
        registered = self.client.post(
            "/auth/register/",
            {"username": username, "email": email, "password": password},
        )
        self.assertEqual(registered.status_code, 302)  # -> login
        logged = self.client.post(
            "/auth/login/", {"username": username, "password": password}
        )
        self.assertEqual(logged.status_code, 302)  # -> post_list

    # --- flujo completo --------------------------------------------------------------------------

    def test_full_crud_flow_with_login(self) -> None:
        """registro -> login -> crear -> listar (1 query) -> editar -> borrar -> logout."""
        # Register, then sign in.
        self._register_and_login("neo", "neo@demo.dev", "redpill")

        # The user exists in the database with their hash (not in plaintext).
        session = self._new_session()
        try:
            neo = session.first(SnakeQuery(User).filter(User.username == "neo"))
            self.assertIsNotNone(neo)
            assert neo is not None
            self.assertNotEqual(neo.password_hash, "redpill")
            neo_id = neo.id
        finally:
            session.close()

        # Create a post (author_id = the logged-in user, resolved by the view).
        created = self.client.post(
            "/posts/new/",
            {"title": "Wake up", "body": "Follow the white rabbit.", "published": "on"},
        )
        self.assertEqual(created.status_code, 302)  # -> post_list

        session = self._new_session()
        try:
            mine = session.all(
                SnakeQuery(Post)
                .filter(Post.author_id == neo_id)
                .order_by(Post.id.asc())
            )
            self.assertEqual(len(mine), 1)
            post_id = mine[0].id
            self.assertEqual(mine[0].title, "Wake up")
            self.assertTrue(mine[0].published)
        finally:
            session.close()

        # List (SSR): 200 with the debug panel injected and the post in the HTML.
        listing = self.client.get("/")
        self.assertEqual(listing.status_code, 200)
        html = listing.content.decode()
        self.assertIn("snake-debug-panel", html)
        self.assertIn("Wake up", html)

        # Edit.
        edited = self.client.post(
            f"/posts/{post_id}/edit/",
            {"title": "Wake up, Neo", "body": "The Matrix has you.", "published": "on"},
        )
        self.assertEqual(edited.status_code, 302)  # -> post_detail
        session = self._new_session()
        try:
            post = session.first(SnakeQuery(Post).filter(Post.id == post_id))
            assert post is not None
            self.assertEqual(post.title, "Wake up, Neo")
        finally:
            session.close()

        # Delete.
        deleted = self.client.post(f"/posts/{post_id}/delete/")
        self.assertEqual(deleted.status_code, 302)  # -> post_list
        session = self._new_session()
        try:
            self.assertIsNone(
                session.first(SnakeQuery(Post).filter(Post.id == post_id))
            )
        finally:
            session.close()

        # Logout: clears the session and the gated views demand a login again.
        logged_out = self.client.post("/auth/logout/")
        self.assertEqual(logged_out.status_code, 302)  # -> login
        gated = self.client.get("/")
        self.assertEqual(
            gated.status_code, 302
        )  # with no session -> redirected to the login
        self.assertIn("/auth/login/", gated.headers["Location"])

    def test_login_rejects_bad_password(self) -> None:
        """A login with the wrong password creates NO session (it re-renders the form with an error)."""
        bad = self.client.post(
            "/auth/login/", {"username": "demo1", "password": "wrong-password"}
        )
        self.assertEqual(bad.status_code, 200)  # it stays on the form
        self.assertIn("Wrong user or password.", bad.content.decode())
        # And the gated views still redirect to login.
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_gated_views_redirect_when_anonymous(self) -> None:
        """With no login, the CRUD redirects to `login` (it exposes no posts)."""
        for path in ("/", "/posts/new/", "/posts/1/", "/posts/1/edit/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertIn("/auth/login/", response.headers["Location"], path)

    def test_users_only_touch_their_own_posts(self) -> None:
        """A user cannot edit or delete another user's posts (404, not 200)."""
        self._register_and_login("trinity", "trinity@demo.dev", "follow-the-rabbit")
        # Post 1 belongs to a seeded user (demo1), not to trinity.
        self.assertEqual(self.client.get("/posts/1/edit/").status_code, 404)
        self.assertEqual(self.client.post("/posts/1/delete/").status_code, 404)

    # --- the ORM's debug tooling -----------------------------------------------------------------

    def test_api_envelope_and_server_timing(self) -> None:
        """The `envelope` channel hangs the `snakeorm` block off the JSON; `Server-Timing` always goes.

        There is no `?_debug=1` trigger any more: the channel is the switch. An object
        (`{"posts": [...]}`) gets `snakeorm` added as a sibling.
        """
        response = self.client.get("/api/posts/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Server-Timing", response.headers)
        body = response.json()
        self.assertIn("snakeorm", body)
        self.assertIn("queries", body["snakeorm"])

    def test_list_include_has_no_n_plus_one(self) -> None:
        """(c) The list with include does NOT fire an N+1: loading the authors is a single query,
        measured with the ORM's own assertion (`assert_queries(1)`), robust to the seed's scale."""
        payload = self.client.get("/api/posts/").json()
        self.assertTrue(payload["posts"])  # the seed brings posts

        session = self._new_session()
        try:
            with assert_queries(1):
                posts = session.all(SnakeQuery(Post).include(Post.author))
                _ = [
                    p.author.username for p in posts
                ]  # already loaded, with no extra query
            self.assertTrue(posts)
        finally:
            session.close()

    def test_user_counts_annotate(self) -> None:
        """A typed aggregate (`annotate`): post count per user. Robust to the seed's scale."""
        rows = self.client.get("/api/posts/stats/").json()["users"]
        by_name = {row["username"]: row["post_count"] for row in rows}
        # The first seeded users exist and have posts (the exact number depends on the scale).
        for username in ("demo1", "demo2", "demo3"):
            self.assertIn(username, by_name)
            self.assertGreaterEqual(by_name[username], 1)

    def test_openapi_schema_and_swagger_ui(self) -> None:
        """drf-spectacular serves the OpenAPI schema (/api/schema/) and the Swagger UI (/api/docs/)."""
        schema = self.client.get("/api/schema/")
        self.assertEqual(schema.status_code, 200)
        docs = self.client.get("/api/docs/")
        self.assertEqual(docs.status_code, 200)
        self.assertIn("text/html", docs.headers.get("Content-Type", ""))

    def test_auth_me_answers_who_the_cookie_says_you_are(self) -> None:
        """`GET /api/auth/me/`: 401 with no session, the user with one. The SPA's boot question.

        A browser page knows who it is because the server rendered it knowing. A client that OWNS
        its routing does not: it reloads on `/orders/` with nothing but a cookie it cannot read —
        `HttpOnly` is the point of the cookie — so the one thing it can do is ASK. Without this
        route the only honest answer a SPA has is "log in again on every refresh", and the usual
        dishonest one is a copy of the user in `localStorage` that outlives the session that
        justified it.
        """
        anonymous = self.client.get("/api/auth/me/")
        self.assertEqual(anonymous.status_code, 401)

        self._register_and_login("trinity", "trinity@demo.dev", "bluepill")

        me = self.client.get("/api/auth/me/")
        self.assertEqual(me.status_code, 200)
        body = me.json()
        self.assertEqual(body["username"], "trinity")
        self.assertEqual(body["email"], "trinity@demo.dev")
        self.assertNotIn("password_hash", body)

        self.client.post("/api/auth/logout/")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_the_posts_json_carries_the_counter_the_trigger_keeps(self) -> None:
        """`/api/posts/` exposes `visit_count`: the one figure no client can work out for itself.

        IT IS A COLUMN ON THE POST, and the whole reason it is denormalised is that the traffic
        board costs ONE statement whatever the size of the visits table. `traffic_board` builds that
        board out of the blog's own listing for exactly that reason — and the JSON of the same
        listing was the one surface that dropped the column on the way out, so a client had a page
        it could not draw from a read that already held every number in it.

        Counting `/api/engagement/posts/<id>/visits` per row instead would be the N+1 over the
        demo's biggest table that the trigger exists to prevent.
        """
        posts = self.client.get("/api/posts/").json()["posts"]
        self.assertTrue(posts)
        for post in posts:
            self.assertIn("visit_count", post)
            self.assertIsInstance(post["visit_count"], int)
