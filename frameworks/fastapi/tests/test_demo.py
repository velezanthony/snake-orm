"""Verification of the FastAPI + SnakeORM demo with `TestClient` (no server started).

It walks the app's real flow (BFF routes, EVERYTHING under `/api/`): register -> login (cookie) ->
create a post -> list the public showcase (include = 1 query, no N+1) -> edit -> delete -> logout. It
also checks the ORM's debug tooling: the `snakeorm` block in the JSON with the `envelope` channel on
(the channel is the switch), the `Server-Timing` header always, and that WRITING with no session
gives 401 (reading is public).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# The app uses SQLite (no `frameworks/.env`); it sets the debug channels BEFORE importing the app.
os.environ["SNAKE_ORM_DEBUG"] = "envelope,timing,sidecar"

from fastapi.testclient import TestClient  # noqa: E402

from snakeorm import SnakeQuery  # noqa: E402
from snakeorm.debug import assert_queries  # noqa: E402

from main import app  # noqa: E402
from shared import config  # noqa: E402
from shared.models import Post, User  # noqa: E402


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """A client with the lifecycle active: `lifespan` creates the schema and seeds it on startup."""
    with TestClient(app) as test_client:
        yield test_client


def _register_and_login(
    client: TestClient, username: str, email: str, password: str
) -> None:
    """Registers a new user and logs in (leaving the session cookie on the client)."""
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert login.status_code == 200, login.text


def test_reading_is_public_writing_is_gated(client: TestClient) -> None:
    """The showcase is public (`GET /api/posts` -> 200); writing with no session gives 401."""
    assert client.get("/api/posts").status_code == 200
    unauthorized = client.post(
        "/api/posts", json={"title": "x", "body": "y", "published": False}
    )
    assert unauthorized.status_code == 401


def test_login_with_seeded_user(client: TestClient) -> None:
    """The seeder leaves real users behind: `demo1` can log in with its demo password."""
    response = client.post(
        "/api/auth/login", json={"username": "demo1", "password": "test1234"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "demo1"
    # The password hash is never leaked.
    assert "password_hash" not in response.json()


def test_login_rejects_bad_password(client: TestClient) -> None:
    """A wrong password -> 401 (it does not reveal whether the user exists)."""
    response = client.post(
        "/api/auth/login", json={"username": "demo1", "password": "nope"}
    )
    assert response.status_code == 401


def test_full_crud_flow(client: TestClient) -> None:
    """The full flow: register -> login -> create -> see it in the showcase -> edit -> delete -> logout."""
    _register_and_login(client, "bob", "bob@demo.dev", "hunter2")

    # Create: the author comes from the session, not from the body.
    created = client.post(
        "/api/posts", json={"title": "First", "body": "hello", "published": False}
    )
    assert created.status_code == 201
    post_id = created.json()["id"]
    assert created.json()["author_id"] is not None

    # The showcase is public and brings ALL posts with their author loaded (include): the one just
    # created shows up with its author `bob`. The debug `envelope` channel wraps arrays in
    # `{"data": [...], "snakeorm": {...}}`, so the list is read from `data`.
    listed = client.get("/api/posts").json()["posts"]
    mine = next(p for p in listed if p["id"] == post_id)
    assert mine["author"]["username"] == "bob"

    # Edit with a PARTIAL patch: only the fields sent are touched.
    edited = client.patch(
        f"/api/posts/{post_id}", json={"published": True, "title": "Edited"}
    )
    assert edited.status_code == 200
    assert edited.json()["published"] is True
    assert edited.json()["title"] == "Edited"

    # Delete.
    deleted = client.delete(f"/api/posts/{post_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/posts/{post_id}").status_code == 404

    # Logout: the session closes and WRITING is shut again (reading stays public).
    assert client.post("/api/auth/logout").status_code == 200
    assert (
        client.post("/api/posts", json={"title": "x", "body": "y"}).status_code == 401
    )


def test_posts_listing_is_public_and_loads_author(client: TestClient) -> None:
    """The public showcase lists the seeded posts with their author loaded, with NO session."""
    # The `envelope` channel wraps arrays in `{"data": [...], "snakeorm": {...}}`.
    listed = client.get("/api/posts").json()["posts"]
    assert len(listed) > 0
    assert all("author" in p for p in listed)


def test_posts_stats_aggregates_per_user(client: TestClient) -> None:
    """`GET /api/posts/stats` returns the post count per user (a typed aggregate), public."""
    body = client.get("/api/posts/stats").json()
    assert "users" in body
    assert body["users"]
    first = body["users"][0]
    assert {"id", "username", "post_count"} <= set(first)


def test_list_include_is_one_query_no_n_plus_one(client: TestClient) -> None:
    """`include(Post.author)` runs ONE single query (a JOIN), no N+1, checked with `assert_queries`.

    It is verified against a direct ORM session: `demo1` (seeded) has SEVERAL posts; listing them with
    `include` must be a single SELECT with a JOIN, not 1 + N (the exact number depends on the seeder's
    scale, so what is asserted is "several", not a fixed figure).
    """
    session = config.make_session("fastapi")
    try:
        demo1 = session.first(SnakeQuery(User).filter(User.username == "demo1"))
        assert demo1 is not None
        with assert_queries(1):
            posts = session.all(
                SnakeQuery(Post).filter(Post.author_id == demo1.id).include(Post.author)
            )
        # The relation came loaded: touching the author does NOT fire a second query.
        assert all(p.author is not None for p in posts)
        assert len(posts) >= 2
    finally:
        session.close()


def test_debug_envelope_appears_on_object_responses(client: TestClient) -> None:
    """The `envelope` channel adds the `snakeorm` sidecar (summary + queries) to OBJECT JSON."""
    _register_and_login(client, "dave", "dave@demo.dev", "passwd")
    created = client.post("/api/posts", json={"title": "T", "body": "B"})
    post_id = created.json()["id"]

    response = client.get(f"/api/posts/{post_id}")
    assert response.status_code == 200
    body = response.json()
    assert "snakeorm" in body
    assert "summary" in body["snakeorm"]
    assert isinstance(body["snakeorm"]["queries"], list) and body["snakeorm"]["queries"]


def test_debug_envelope_wraps_list_responses(client: TestClient) -> None:
    """On an ARRAY the `envelope` channel wraps: `{"data": [...], "snakeorm": {...}}`.

    It asks `/api/accounts/roles` and no longer `/api/posts`, and the swap is the point rather than
    a detail: the blog listing now answers `{"posts": [...]}`, which is the envelope the other two
    demos use for it. This test is about the MIDDLEWARE — what it does when a route hands it a
    top-level array — so it needs a route that still hands it one, not the blog.
    """
    _register_and_login(client, "erin", "erin@demo.dev", "passwd")
    body = client.get("/api/accounts/roles").json()
    assert isinstance(body["data"], list)
    assert "summary" in body["snakeorm"]


def test_server_timing_header_is_always_present(client: TestClient) -> None:
    """The `timing` channel ALWAYS adds the `Server-Timing` header (W3C) to every response."""
    response = client.get(
        "/api/posts"
    )  # the public showcase, the header goes out just the same
    assert "server-timing" in {k.lower() for k in response.headers}


def test_sidecar_panel_is_served(client: TestClient) -> None:
    """The `sidecar` channel exposes `X-Debug-Token` and serves the HTML panel at `/__snake__/{token}`."""
    response = client.get("/")
    token = response.headers.get("x-debug-token")
    assert token, "the sidecar channel's X-Debug-Token header was expected"

    panel = client.get(f"/__snake__/{token}")
    assert panel.status_code == 200
    assert "text/html" in panel.headers["content-type"]
    assert "snake-debug-panel" in panel.text
