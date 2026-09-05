"""Verification of the Flask + SnakeORM demo WITHOUT booting a server (it uses `app.test_client()`).

It walks the app's full flow: register -> login -> create post -> list -> edit -> delete -> logout,
and along the way it checks what belongs to the ORM and to its debug tooling:

  (a) The SSR listing returns HTML with the debug panel injected (`snake-debug-panel`).
  (b) An `/api/` endpoint carries the `snakeorm` block as long as the `envelope` channel is on (the
      channel is the switch) and ALWAYS the `Server-Timing` header.
  (c) Listing posts with `include(Post.author)` runs ONE single query (no N+1), via `assert_queries`.
  (g) The inventory SSR pages: the five of the page taxonomy over a COMPOSITE key, plus the sidebar
      that carries the section catalogue into every one of them.
  (h) The orders SSR pages: the same five over a plain key, plus the three OPERATIONS the domain
      exists for — the row lock, the savepoint and the isolation level, driven by an HTTP POST.
  (i) The two pages phase 4 added everywhere plus the billing domain's three: the reports, whose
      figures are aggregates and whose tables say which ORM feature produced them, and the CSV
      exports, whose whole subject is that they are never built in memory.

The inventory block asserts through the DATABASE and not only through the HTML. A page that renders
proves the template compiles; what a wrapper gets wrong is the round trip — a form that posts back
half a composite key still redirects somewhere plausible, and with one warehouse seeded it even
edits the right row. So every write here is read back with `config.make_session("flask")`.

The orders block goes one further, because the thing it is checking is not visible in a response at
all: the three operations DECLARE their isolation level as the first statement of their transaction,
and Flask's app-wide `before_app_request` hook can have spent that transaction before the handler is
even entered. Postgres accepts the declaration silently when it would not change the level, so the
mistake is invisible on the machine it is written on and fatal on MySQL. It is pinned by asking the
session, from inside the operation, for a level it does NOT already have — the one shape of the
mistake the engine is loud about.

It can be run two ways:

    uv run python frameworks/flask/verify.py      # script: prints a summary and exits 0/1
    uv run pytest frameworks/flask/verify.py       # as a test suite (test_* functions)

Every test reseeds the DB (autouse fixture), so they are independent of ordering.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

# Lets the demo modules be imported both from the repo root and from here.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from flask import Response
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from snakeorm import (
    SnakeIsolation,
    SnakeQuery,
    SnakeSession,
    SnakeUnsupportedFeature,
)
from snakeorm.debug import assert_queries, capture_queries

from app import create_app
from apps.billing import selectors as billing_selectors
from apps.billing import usecases as billing_usecases
from apps.inventory import selectors as inventory_selectors
from apps.inventory import urls as inventory_urls
from apps.inventory import viewmodels as inventory_viewmodels
from apps.orders import selectors as orders_selectors
from apps.orders import usecases as orders_usecases
from apps.orders import viewmodels as orders_viewmodels
from apps.orders.models import Order, OrderState
from apps.orders.usecases import Failure
from seed import reset_and_seed
from shared import config
from shared.models import Post

# The app is BUILT here, not imported ready-made. `app.py` stopped calling its own factory so that
# importing it does not rebuild the database — which it did, on every reloader cycle and every time
# a tool looked at the models. Flask finds `create_app` on its own, and a test that wants an app
# asks for one.
app = create_app()


@pytest.fixture(autouse=True)
def _reset_db() -> None:
    """Leave the DB in its CLEAN seeded state before every test (drop + migrate + seed)."""
    reset_and_seed()


@pytest.fixture
def client() -> Iterator[FlaskClient]:
    """A test client with its own cookie context (for the login session)."""
    with app.test_client() as test_client:
        yield test_client


def _register(
    client: FlaskClient, username: str, email: str, password: str
) -> TestResponse:
    """Register a user through the SSR form (it follows the success redirect)."""
    return client.post(
        "/auth/register",
        data={"username": username, "email": email, "password": password},
        follow_redirects=True,
    )


def _login(client: FlaskClient, username: str, password: str) -> TestResponse:
    """Log in through the SSR form."""
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def test_auth_and_post_crud_roundtrip() -> None:
    """Full flow: register -> login -> create -> list -> edit -> delete -> logout (all SSR)."""
    client = app.test_client()

    # With no session the CRUD is gated: asking for /posts redirects to the login.
    gated = client.get("/posts")
    assert gated.status_code == 302
    assert "/auth/login" in gated.headers["Location"]

    # Register (it logs you in automatically) and land on the listing.
    registered = _register(client, "neo", "neo@demo.dev", "the-matrix")
    assert registered.status_code == 200
    assert "Posts" in registered.get_data(as_text=True)

    # Logout and explicit re-login, to exercise verify_password.
    client.post("/auth/logout")
    assert client.get("/posts").status_code == 302  # no session anymore
    logged = _login(client, "neo", "the-matrix")
    assert logged.status_code == 200

    # Create a post of our own (it follows the redirect to the detail page).
    created = client.post(
        "/posts/new",
        data={"title": "Mi primer post", "body": "hola mundo", "published": "on"},
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert "Mi primer post" in created.get_data(as_text=True)

    # It shows up in the listing, with edit controls because it belongs to us.
    listing = client.get("/posts").get_data(as_text=True)
    assert "Mi primer post" in listing
    assert "Edit" in listing

    # Find the id of the freshly created post by querying the ORM directly.
    session = config.make_session("flask")
    try:
        mine = session.first(SnakeQuery(Post).filter(Post.title == "Mi primer post"))
        assert mine is not None
        post_id = mine.id
    finally:
        session.close()

    # Edit our own post.
    edited = client.post(
        f"/posts/{post_id}/edit",
        data={"title": "Post editado", "body": "contenido nuevo"},
        follow_redirects=True,
    )
    assert edited.status_code == 200
    assert "Post editado" in edited.get_data(as_text=True)

    # Delete our own post.
    deleted = client.post(f"/posts/{post_id}/delete", follow_redirects=True)
    assert deleted.status_code == 200
    assert "Post editado" not in deleted.get_data(as_text=True)

    # Final logout: it clears the cookie; the CRUD is gated again.
    client.post("/auth/logout")
    assert client.get("/posts").status_code == 302


def test_cannot_edit_others_posts() -> None:
    """A user can NOT edit somebody else's posts, and the answer is a 404 rather than a 403.

    Telling them apart would confirm the post EXISTS, which is a fact the asker had no right to.
    Both demos answer the same thing now; Flask used to say 403 and Django 404.
    """
    client = app.test_client()
    _login(client, "demo1", "test1234")
    # Post 3 belongs to `demo2` in the seed: editing it must be forbidden.
    forbidden = client.get("/posts/3/edit")
    assert forbidden.status_code == 404


def test_ssr_panel_is_injected() -> None:
    """(a) The SSR listing (logged in) carries the debug panel injected at the end of the HTML."""
    client = app.test_client()
    _login(client, "demo1", "test1234")
    response = client.get("/posts")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "snake-debug-panel" in body, "the debug panel was NOT injected into the HTML"
    # The seed brings posts from every author, with their user loaded.
    assert "demo1" in body


def test_api_envelope_and_server_timing() -> None:
    """(b) `/api/posts` carries the `snakeorm` block (envelope channel) and the Server-Timing header."""
    client = app.test_client()
    response = client.get("/api/posts")
    assert response.status_code == 200
    assert "Server-Timing" in response.headers, "the Server-Timing header is missing"
    payload = json.loads(response.get_data(as_text=True))
    # The `envelope` channel hangs the debug off the `snakeorm` key (on an object, as a sibling; on an
    # array, wrapped in `{data, snakeorm}`). No `?_debug=1` needed: the channel is the switch.
    assert "snakeorm" in payload, (
        "the snakeorm block does NOT travel (envelope channel)"
    )
    assert "summary" in payload["snakeorm"]


def test_the_post_detail_answers_the_post_and_not_a_wrapper() -> None:
    """`/api/posts/<id>` answers the post FLAT, the same shape Django and FastAPI answer with.

    This demo used to wrap it — `{"post": {...}}` — and the other two did not, so the shape of the
    blog's detail depended on WHICH DEMO answered, on an endpoint all three exist to mirror. A
    client that can switch backends is what found it: it read `title`, got `undefined`, and drew a
    post with no title and an author of `#undefined`.

    THE FLAT ONE IS THE CORRECT ONE, and the argument is written down in `django/apps/blog/
    serializers.py`: the envelope exists so the `envelope` channel can inject `snakeorm` INSIDE an
    object, and a post already IS an object. The LISTING needs one because it is an array, which is
    why `/api/posts` keeps its `{"posts": [...]}` on all three.
    """
    client = app.test_client()
    payload = json.loads(client.get("/api/posts/1").get_data(as_text=True))

    assert "post" not in payload, (
        "the post is wrapped again; the other two demos answer it flat"
    )
    assert payload["id"] == 1
    assert isinstance(payload["title"], str)
    assert payload["author"]["username"]
    assert "password_hash" not in payload["author"]


def test_openapi_spec_is_served() -> None:
    """flask-smorest exposes the OpenAPI at /api/openapi.json with the three endpoints documented."""
    client = app.test_client()
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    spec = json.loads(response.get_data(as_text=True))
    assert spec["openapi"].startswith("3.")
    assert {"/api/posts", "/api/posts/{post_id}", "/api/posts/stats"} <= set(
        spec["paths"]
    )


def test_swagger_ui_is_served() -> None:
    """The Swagger UI is served as HTML at /api/docs."""
    client = app.test_client()
    response = client.get("/api/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("Content-Type", "")


def test_include_has_no_n_plus_one() -> None:
    """(c) Listing N posts with `include(Post.author)` runs ONE single query (no N+1)."""
    session = config.make_session("flask")
    try:
        with assert_queries(1):
            posts = session.all(SnakeQuery(Post).include(Post.author))
            # Touching each post's author does NOT fire extra queries: it came loaded already.
            _ = [p.author.username for p in posts]
        # The point is the `assert_queries(1)` above (no N+1); the exact count depends on the scale.
        assert posts
    finally:
        session.close()


def test_inventory_crud_over_the_composite_key() -> None:
    """(f) The inventory CRUD over HTTP: the route carries BOTH halves of the key, and 409 refuses.

    The logic is in `shared` and its suite already pins it. What this proves is the part only the
    wrapper can get wrong: that a stock row is addressed by warehouse AND sku, that a `conflict`
    reason becomes a 409, and that the price survives the JSON as exact text.
    """
    web = app.test_client()
    warehouses = web.get("/api/inventory/warehouses").get_json()
    rows = warehouses["data"] if isinstance(warehouses, dict) else warehouses
    assert rows, "the seeding left no warehouses"
    warehouse_id = rows[0]["id"]

    created = web.post(
        "/api/inventory/skus",
        json={
            "name": "Verify widget",
            "kind": "physical",
            "price": "12.34",
            "weight_kg": 1.5,
            "lead_time_days": 2,
        },
    )
    assert created.status_code == 201, created.get_json()
    sku_id = created.get_json()["id"]
    assert created.get_json()["price"] == "12.34"

    base = f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}"
    received = web.post(f"{base}/receive", json={"units": 4})
    assert received.status_code == 200, received.get_json()
    assert received.get_json()["on_hand"] == 4

    refused = web.post(f"{base}/ship", json={"units": 9})
    assert refused.status_code == 409, "shipping more than there is has to refuse"

    movements = web.get(f"{base}/movements").get_json()
    moved = movements["data"] if isinstance(movements, dict) else movements
    assert [m["delta"] for m in moved] == [4], "the refusal must not leave a movement"

    # The three verbs over ONE pair, which the pages had and the API did not. PATCH corrects a row
    # that exists; a pair that vanished between the form being drawn and being submitted is a 404
    # rather than a silent insert, which is the whole difference from the PUT upsert.
    corrected = web.patch(base, json={"on_hand": 4, "reserved": 2})
    assert corrected.status_code == 200, corrected.get_json()
    assert corrected.get_json()["reserved"] == 2
    ghost = f"/api/inventory/warehouses/{warehouse_id}/stock/999999"
    assert web.patch(ghost, json={"on_hand": 1, "reserved": 0}).status_code == 404

    # DELETE refuses a pair with history: the movements are the audit trail and the FK is RESTRICT,
    # so a pair that has moved gets CLOSED, not deleted. Same answer the delete page gives.
    assert web.delete(base).status_code == 409, (
        "a pair with movements cannot be deleted"
    )

    spare = web.post(
        "/api/inventory/skus",
        json={
            "name": "Spare",
            "kind": "physical",
            "price": "1.00",
            "weight_kg": 0.1,
            "lead_time_days": 1,
        },
    ).get_json()["id"]
    untouched = f"/api/inventory/warehouses/{warehouse_id}/stock/{spare}"
    assert web.put(untouched, json={"on_hand": 3}).status_code == 200
    assert web.delete(untouched).status_code == 204, "a pair nobody moved is deletable"


# ---- (g) The inventory SSR pages ---------------------------------------------------------------


def test_the_catalogue_page_makes_a_warehouse_and_a_sku() -> None:
    """(g) The two things a stock pair points at, made from a page for the first time.

    Until this page existed the demo could only stock what the seeder had built: every other page
    here is about what is IN the inventory, and neither of these is.
    """
    client = app.test_client()

    made_warehouse = client.post(
        "/inventory/catalogue/warehouses",
        data={
            "code": "ZZY",
            "name": "Made from a page",
            "opened_on": "2021-05-04",
            "shift_start": "07:00",
            "cutoff": "19:00",
        },
        follow_redirects=True,
    )
    made_sku = client.post(
        "/inventory/catalogue/skus",
        data={
            "name": "Page widget",
            "kind": "physical",
            "price": "12.50",
            "weight_kg": "0.8",
            "lead_time_days": "3",
        },
        follow_redirects=True,
    )

    assert made_warehouse.status_code == 200
    assert made_sku.status_code == 200
    body = client.get("/inventory/catalogue").get_data(as_text=True)
    assert "ZZY" in body
    assert "Page widget" in body


def test_a_warehouse_code_of_four_characters_is_REFUSED() -> None:
    """(g) The ORM shouts rather than truncating, and the page turns that into something readable.

    A code silently trimmed to three letters is the failure this repository's doctrine is against:
    it would be stored, it would look right, and nobody would find out until a lookup by the code
    somebody actually typed came back empty.
    """
    client = app.test_client()

    refused = client.post(
        "/inventory/catalogue/warehouses",
        data={
            "code": "ZZZZ",
            "name": "Too long for a code",
            "opened_on": "2021-05-04",
            "shift_start": "07:00",
            "cutoff": "19:00",
        },
        follow_redirects=True,
    )

    assert refused.status_code == 200
    body = client.get("/inventory/catalogue").get_data(as_text=True)
    assert "Too long for a code" not in body


def test_reserving_across_a_warehouse_holds_units_on_every_pair() -> None:
    """(g) The bulk hold: one UPDATE over the whole warehouse, not a loop over its pairs.

    It lives on the catalogue page and not on a pair's, because it is not about a pair.
    """
    warehouse_id, sku_id = _first_pair()
    before = _levels(warehouse_id, sku_id)
    assert before is not None

    held = app.test_client().post(
        f"/inventory/catalogue/warehouses/{warehouse_id}/reserve",
        data={"units": 1},
        follow_redirects=True,
    )

    assert held.status_code == 200
    after = _levels(warehouse_id, sku_id)
    assert after is not None
    assert after[1] == before[1] + 1


def test_receiving_units_from_the_detail_page_moves_the_pair() -> None:
    """(g) A movement made from the page the pair is on, and the pair moves by exactly that much.

    The form lives on the DETAIL page rather than on one of its own, and that is the catalogue
    holding: `orders` has an `operate` page because an operation there is something you go looking
    for, and a movement is something you do to the pair in front of you — with its history right
    underneath it.
    """
    warehouse_id, sku_id = _first_pair()
    before = _levels(warehouse_id, sku_id)
    assert before is not None

    moved = app.test_client().post(
        f"/inventory/detail/{warehouse_id}/{sku_id}/receive",
        data={"units": 6},
        follow_redirects=True,
    )

    assert moved.status_code == 200
    after = _levels(warehouse_id, sku_id)
    assert after is not None
    assert after[0] == before[0] + 6


def test_shipping_more_than_there_is_from_the_page_writes_NOTHING() -> None:
    """(g) The refusal comes back to the page and the pair is untouched.

    Without the check the negative row reaches the engine and the CHECK catches it three layers
    down, inside a commit, with a driver error nobody can render.
    """
    warehouse_id, sku_id = _first_pair()
    before = _levels(warehouse_id, sku_id)
    assert before is not None

    refused = app.test_client().post(
        f"/inventory/detail/{warehouse_id}/{sku_id}/ship",
        data={"units": before[0] + 1000},
        follow_redirects=True,
    )

    assert refused.status_code == 200
    assert _levels(warehouse_id, sku_id) == before


def _first_pair() -> tuple[int, int]:
    """The first `(warehouse_id, sku_id)` the listing shows, read out of the page's own HTML.

    Out of the HTML and not out of the database on purpose: what is being pinned is that BOTH halves
    of the key reach the link. A pair invented in the test would still be a valid URL, so the page
    could be emitting `/inventory/detail/1/` and the test would sail past it.
    """
    body = app.test_client().get("/inventory/list").get_data(as_text=True)
    pairs = re.findall(r"/inventory/detail/(\d+)/(\d+)", body)
    assert pairs, "the listing linked to no pair at all"
    return int(pairs[0][0]), int(pairs[0][1])


def _free_pair() -> tuple[int, int]:
    """A `(warehouse, sku)` that holds NOTHING yet, so `create` is an insert and not a recount."""
    session = config.make_session("flask")
    try:
        warehouse = inventory_selectors.list_warehouses(session)[0]
        taken = {
            stock.sku_id
            for stock in inventory_selectors.stock_of_warehouse(session, warehouse.id)
        }
        free = [
            sku for sku in inventory_selectors.list_skus(session) if sku.id not in taken
        ]
        assert free, "every SKU already has stock in that warehouse"
        return warehouse.id, free[0].id
    finally:
        session.close()


def _pager_total(body: str) -> int:
    """How many rows the pager of a listing claims there are, in TOTAL and not on the page shown."""
    found = re.search(r"· (\d+) row\(s\)", body)
    assert found is not None, "the page carries no pager to read a total off"
    return int(found.group(1))


def _levels(warehouse_id: int, sku_id: int) -> tuple[int, int] | None:
    """The `(on_hand, reserved)` a pair holds in the DATABASE, or `None` if there is no such pair."""
    session = config.make_session("flask")
    try:
        stock = inventory_selectors.get_stock(session, warehouse_id, sku_id)
        return None if stock is None else (stock.on_hand, stock.reserved)
    finally:
        session.close()


def test_inventory_list_renders_its_rows_and_a_real_pager() -> None:
    """(g) The listing paints rows and a pager whose FIRST page says so on its `Previous` edge.

    The edge is the half worth pinning. `Previous` on page one is a `<span aria-disabled="true">` and
    not a disabled `<a>`, because HTML has no such thing and an `<a>` with no `href` is skipped by the
    keyboard entirely — the edge of a paginated list would go silent for the people who most need to
    be told where the edge is.
    """
    body = app.test_client().get("/inventory/list").get_data(as_text=True)

    assert "/inventory/detail/" in body, "the listing shows no stock row"
    assert 'class="pager"' in body
    assert (
        '<span class="btn btn-ghost btn-md" aria-disabled="true">Previous</span>'
        in body
    )
    assert 'rel="next"' in body, "the seed is big enough to have a second page"


def test_inventory_filter_narrows_the_listing_to_one_warehouse() -> None:
    """(g) `?warehouse=` filters, and it narrows: the total drops and the option comes back selected."""
    client = app.test_client()
    session = config.make_session("flask")
    try:
        warehouse = inventory_selectors.list_warehouses(session)[0]
        held = len(inventory_selectors.stock_of_warehouse(session, warehouse.id))
    finally:
        session.close()

    everything = client.get("/inventory/list").get_data(as_text=True)
    filtered = client.get(f"/inventory/list?warehouse={warehouse.id}").get_data(
        as_text=True
    )

    total, narrowed = _pager_total(everything), _pager_total(filtered)
    assert narrowed == held < total, (
        f"{narrowed} rows held, {held} expected, {total} in all"
    )
    assert f'value="{warehouse.id}" selected' in filtered, (
        "the filter forgot which option it is on"
    )


def test_inventory_page_two_is_not_page_one() -> None:
    """(g) The pager is a real LIMIT/OFFSET: the second page shows OTHER pairs, not the same ones."""
    client = app.test_client()

    first = set(
        re.findall(
            r"/inventory/detail/(\d+/\d+)",
            client.get("/inventory/list").get_data(as_text=True),
        )
    )
    second = set(
        re.findall(
            r"/inventory/detail/(\d+/\d+)",
            client.get("/inventory/list?page=2").get_data(as_text=True),
        )
    )

    assert first and second
    assert not (first & second), (
        f"both pages show the same pairs: {sorted(first & second)}"
    )


def test_inventory_detail_shows_a_pair_and_a_bad_pair_is_a_404() -> None:
    """(g) The detail resolves BOTH halves of the key, and a pair nobody holds answers 404.

    The 404 uses a real sku id with a warehouse id that does not exist, so what is being refused is
    the PAIR and not merely a number out of range.
    """
    warehouse_id, sku_id = _first_pair()
    client = app.test_client()

    found = client.get(f"/inventory/detail/{warehouse_id}/{sku_id}")
    assert found.status_code == 200
    body = found.get_data(as_text=True)
    assert f"pair {warehouse_id}/{sku_id}" in body
    assert "Movements" in body

    assert client.get(f"/inventory/detail/999999/{sku_id}").status_code == 404


def test_inventory_create_round_trips_to_the_database() -> None:
    """(g) The create form posts BOTH halves of the key and the row lands in the DB with them.

    Read back through a session of its own rather than off the redirect: the page after a redirect is
    rendered from the same request that wrote, so it can agree with a write that was never committed.
    """
    warehouse_id, sku_id = _free_pair()
    assert _levels(warehouse_id, sku_id) is None, "the pair was supposed to be free"

    created = app.test_client().post(
        "/inventory/create",
        data={"warehouse_id": warehouse_id, "sku_id": sku_id, "on_hand": 7},
        follow_redirects=True,
    )

    assert created.status_code == 200
    assert _levels(warehouse_id, sku_id) == (7, 0)


def test_inventory_update_changes_the_levels() -> None:
    """(g) The update writes both levels, and the KEY comes from the URL rather than from the form.

    The form posts a warehouse and a SKU of somebody else's row on purpose: they are ignored, because
    a composite key is not editable — changing it does not edit this row, it means a different one.
    """
    warehouse_id, sku_id = _first_pair()
    before = _levels(warehouse_id, sku_id)
    assert before is not None

    updated = app.test_client().post(
        f"/inventory/update/{warehouse_id}/{sku_id}",
        data={
            "warehouse_id": 999999,
            "sku_id": 999999,
            "on_hand": 41,
            "reserved": 5,
        },
        follow_redirects=True,
    )

    assert updated.status_code == 200
    assert _levels(warehouse_id, sku_id) == (41, 5)


def test_inventory_delete_is_refused_when_it_would_orphan_the_history() -> None:
    """(g) FK RESTRICT, said in words BEFORE the button: a pair with movements cannot be deleted.

    Both halves are checked — the confirmation page states it, and the POST states it again for
    whoever got there past the page. And the row is still in the database afterwards, which is the
    only proof that the refusal happened instead of being merely announced.
    """
    warehouse_id, sku_id = _first_pair()
    session = config.make_session("flask")
    try:
        movements = len(inventory_selectors.movements_of(session, warehouse_id, sku_id))
    finally:
        session.close()
    assert movements > 0, "the seed left the first pair with no history to protect"

    client = app.test_client()
    confirmation = client.get(f"/inventory/delete/{warehouse_id}/{sku_id}").get_data(
        as_text=True
    )
    assert "cannot be deleted" in confirmation
    assert f"{movements}</strong> movement(s)" in confirmation

    refused = client.post(
        f"/inventory/delete/{warehouse_id}/{sku_id}", follow_redirects=True
    )
    assert "cannot be deleted" in refused.get_data(as_text=True)
    assert _levels(warehouse_id, sku_id) is not None, "the row went anyway"


def test_the_sidebar_is_on_every_page_and_marks_the_one_you_are_on() -> None:
    """(g) The section catalogue reaches EVERY page, and `aria-current` says which one is open.

    On the app and not on a blueprint, which is what this walks: the blog, the inventory, the lab and
    an auth form are four different blueprints, and a sidebar registered on one of them would be a
    shell that renders differently depending on who answered.
    """
    client = app.test_client()
    _login(client, "demo1", "test1234")

    for path in (
        "/posts",
        "/inventory/list",
        "/orders/list",
        "/lab/list",
        "/auth/login",
    ):
        body = client.get(path, follow_redirects=True).get_data(as_text=True)
        assert '<nav class="sidebar" aria-label="Domains">' in body, path
        assert 'href="/inventory/list"' in body, path
        assert "sidebar-blurb" in body, path

    open_page = client.get("/inventory/list").get_data(as_text=True)
    assert (
        '<a class="sidebar-link" href="/inventory/list" aria-current="page">'
        in open_page
    )
    assert (
        '<a class="sidebar-link" href="/lab/list" aria-current="page">' not in open_page
    )


# ---- (h) The orders SSR pages and their three operations ---------------------------------------


def _orders_total(body: str) -> int:
    """How many orders the pager of a listing claims there are, in TOTAL and not on the page shown."""
    found = re.search(r"· (\d+) order\(s\)", body)
    assert found is not None, "the page carries no pager to read a total off"
    return int(found.group(1))


def _first_order_id() -> int:
    """The first order id the listing links to, read out of the page's own HTML.

    Out of the HTML rather than out of the database, for the same reason `_first_pair` does it: what
    is being pinned is that the link the page emits resolves. An id invented in the test would be a
    valid URL whatever the template got wrong.
    """
    body = app.test_client().get("/orders/list").get_data(as_text=True)
    ids = re.findall(r"/orders/detail/(\d+)", body)
    assert ids, "the listing linked to no order at all"
    return int(ids[0])


def _order_state(order_id: int) -> str:
    """The state an order is in according to the DATABASE, not according to the page that wrote it."""
    session = config.make_session("flask")
    try:
        order = orders_selectors.get_order(session, order_id)
        assert order is not None, f"order {order_id} is gone"
        return order.state.value
    finally:
        session.close()


def _wanted(order_id: int) -> list[tuple[int, int]]:
    """The `(sku_id, on_hand)` an order asks for, straight from its lines."""
    session = config.make_session("flask")
    try:
        return [
            (line.sku_id, line.quantity)
            for line in orders_selectors.bare_lines_of_order(session, order_id)
        ]
    finally:
        session.close()


def _reserved_units(warehouse_id: int, sku_ids: list[int]) -> dict[int, int]:
    """How many units of each SKU the warehouse is currently HOLDING for somebody.

    `reserved` and not `on_hand`, because a reservation moves exactly that number and leaves the
    shelf alone: the units are still there, they are just promised. A test that watched `on_hand`
    would pass while nothing at all had been held.
    """
    session = config.make_session("flask")
    try:
        held = {}
        for sku_id in sku_ids:
            stock = inventory_selectors.get_stock(session, warehouse_id, sku_id)
            assert stock is not None, f"the pair {warehouse_id}/{sku_id} holds no row"
            held[sku_id] = stock.reserved
        return held
    finally:
        session.close()


def _reservable_order(*, billable: bool = False) -> tuple[int, int]:
    """A DRAFT order the warehouse can actually fill, as `(order_id, warehouse_id)`.

    Found rather than fixed, and it has to be: the seeder deliberately leaves one draft asking for
    more units than its warehouse holds, so a test that took "the first draft" would be pinning the
    refusal path while claiming to pin the happy one.

    `billable=True` narrows it further to a customer who HAS a subscription, which is what `settle`
    bills against — without one the operation is not offered at all, and the settle test would be
    asserting that a button it never pressed did nothing.
    """
    session = config.make_session("flask")
    try:
        drafts = session.all(
            SnakeQuery(Order).filter(Order.state == OrderState.DRAFT).limit(60)
        )
        for order in drafts:
            lines = orders_selectors.bare_lines_of_order(session, order.id)
            if not lines:
                continue
            if billable and not billing_selectors.subscriptions_of_user(
                session, order.customer_id
            ):
                continue
            stock = {
                row.sku_id: row
                for row in inventory_selectors.stock_of_warehouse(
                    session, order.warehouse_id
                )
            }
            if all(
                line.sku_id in stock
                and stock[line.sku_id].on_hand - stock[line.sku_id].reserved
                >= line.quantity
                for line in lines
            ):
                return order.id, order.warehouse_id
    finally:
        session.close()
    raise AssertionError("the seed left no draft order its warehouse can fill")


def _order_in_state(state: OrderState) -> int:
    """The id of some order sitting in a given state. The seeder's first pass covers all five."""
    session = config.make_session("flask")
    try:
        order = session.first(SnakeQuery(Order).filter(Order.state == state))
        assert order is not None, f"the seed left no order in {state.value}"
        return order.id
    finally:
        session.close()


def test_orders_list_renders_its_rows_and_a_real_pager() -> None:
    """(h) The listing paints rows, and its pager is a real LIMIT/OFFSET rather than a decoration.

    Two halves. The FIRST page's `Previous` is a `<span aria-disabled="true">` and not a disabled
    `<a>`, because HTML has no such thing and an `<a>` with no `href` is skipped by the keyboard
    entirely. And page two shows OTHER orders — a pager that renders while every page repeats the
    same rows looks exactly like a working one.
    """
    client = app.test_client()
    body = client.get("/orders/list").get_data(as_text=True)

    assert "/orders/detail/" in body, "the listing shows no order"
    assert 'class="pager"' in body
    assert (
        '<span class="btn btn-ghost btn-md" aria-disabled="true">Previous</span>'
        in body
    )
    assert 'rel="next"' in body, "the seed is big enough to have a second page"

    first = set(re.findall(r"/orders/detail/(\d+)", body))
    second = set(
        re.findall(
            r"/orders/detail/(\d+)",
            client.get("/orders/list?page=2").get_data(as_text=True),
        )
    )
    assert first and second
    assert not (first & second), (
        f"both pages show the same orders: {sorted(first & second)}"
    )


def test_orders_state_filter_narrows_the_listing() -> None:
    """(h) `?state=` narrows the listing, comes back selected, and a nonsense value shows everything.

    The last third is the one worth writing down: an unknown state is NOT the same case as the
    inventory's unknown warehouse id. An id is still a filter the engine can run and correctly
    matches nothing; a state the enum refuses to build cannot become a filter at all, so the choice
    is between showing everything and raising at a hand-edited URL. A typo in a query string is not
    a 500, and `parse_state` is where that decision lives for both demos at once.
    """
    client = app.test_client()
    session = config.make_session("flask")
    try:
        drafts = orders_selectors.count_orders(session, state=OrderState.DRAFT)
    finally:
        session.close()

    everything = client.get("/orders/list").get_data(as_text=True)
    filtered = client.get("/orders/list?state=draft").get_data(as_text=True)
    nonsense = client.get("/orders/list?state=in-a-hurry").get_data(as_text=True)

    assert _orders_total(filtered) == drafts < _orders_total(everything)
    assert 'value="draft" selected' in filtered, (
        "the filter forgot which option it is on"
    )
    assert _orders_total(nonsense) == _orders_total(everything)


def test_orders_detail_shows_an_order_and_a_bad_id_is_a_404() -> None:
    """(h) The detail resolves the order with its three parties and its lines; an unknown id is a 404."""
    order_id = _first_order_id()
    client = app.test_client()

    found = client.get(f"/orders/detail/{order_id}")
    assert found.status_code == 200
    body = found.get_data(as_text=True)
    assert "Sum of the lines" in body
    assert "Lines" in body

    assert client.get("/orders/detail/999999").status_code == 404


def test_orders_create_round_trips_to_the_database() -> None:
    """(h) The creation form places an order AND its lines, and the prices come off the SKUs.

    Read back through a session of its own rather than off the redirect: the page after a redirect is
    rendered from the same request that wrote, so it can agree with a write that was never committed.
    The total is checked as well as the lines, because it is DERIVED and stored — an order whose
    lines landed and whose total did not is a row that adds up to a lie.
    """
    session = config.make_session("flask")
    try:
        warehouse = inventory_selectors.list_warehouses(session)[0]
        stock = inventory_selectors.stock_of_warehouse(session, warehouse.id)[:2]
        found = [inventory_selectors.get_sku(session, row.sku_id) for row in stock]
        customer_id = orders_selectors.customers_with_orders(session)[0].id
    finally:
        session.close()
    # Filtering and then counting, rather than asserting `all(... is not None)`: the assertion reads
    # the same and narrows nothing, so every `skus[0].price` below it was an access on `Sku | None`.
    skus = [sku for sku in found if sku is not None]
    assert len(skus) == 2, (
        "the warehouse did not have two stocked SKUs to price the order with"
    )

    created = app.test_client().post(
        "/orders/create",
        data={
            "reference": "VERIFY-0001",
            "customer_id": customer_id,
            "warehouse_id": warehouse.id,
            # The middle slot is left EMPTY on purpose: the form offers a fixed number of them and
            # the ones nobody filled in must not become lines, nor shift the slot below onto the
            # wrong on_hand.
            "line_sku_id": [str(skus[0].id), "", str(skus[1].id)],
            "line_quantity": ["2", "7", "3"],
        },
        follow_redirects=True,
    )
    assert created.status_code == 200

    session = config.make_session("flask")
    try:
        order = orders_selectors.get_order_by_reference(session, "VERIFY-0001")
        assert order is not None, "the order never reached the database"
        lines = orders_selectors.bare_lines_of_order(session, order.id)
        assert sorted((line.sku_id, line.quantity) for line in lines) == sorted(
            [(skus[0].id, 2), (skus[1].id, 3)]
        )
        assert order.total == skus[0].price * 2 + skus[1].price * 3
    finally:
        session.close()


def test_reserve_holds_the_units_on_the_real_stock_row() -> None:
    """(h) A reservation raises `reserved` on every line's stock row by exactly what the line wants.

    The point of the whole domain, driven through an HTTP POST. `reserved` and not `on_hand`: the
    units are still on the shelf, they are just promised, and a test watching the shelf would pass
    over an operation that held nothing at all.
    """
    order_id, warehouse_id = _reservable_order()
    wanted = _wanted(order_id)
    before = _reserved_units(warehouse_id, [sku_id for sku_id, _ in wanted])

    reserved = app.test_client().post(
        f"/orders/operate/{order_id}/reserve", follow_redirects=True
    )
    assert reserved.status_code == 200

    after = _reserved_units(warehouse_id, [sku_id for sku_id, _ in wanted])
    assert after == {sku_id: before[sku_id] + units for sku_id, units in wanted}
    assert _order_state(order_id) == "reserved"


def test_settle_bills_a_reserved_order_and_takes_it_to_settled() -> None:
    """(h) Reserve then settle: the order reaches SETTLED and comes back carrying an invoice.

    The subscription is read out of the operations page's own `<select>` rather than picked in the
    test, and that is the half worth pinning: `settle` refuses a subscription belonging to anybody
    but the order's customer, so a page offering the wrong ones would be handing the user a refusal
    to click on. Taking the id from the page proves the page offered a usable one.
    """
    order_id, _ = _reservable_order(billable=True)
    client = app.test_client()
    assert (
        client.post(
            f"/orders/operate/{order_id}/reserve", follow_redirects=True
        ).status_code
        == 200
    )

    page = client.get(f"/orders/operate/{order_id}").get_data(as_text=True)
    offered = re.search(r'name="subscription_id".*?<option value="(\d+)"', page, re.S)
    assert offered is not None, "the page offered no subscription to bill against"

    settled = client.post(
        f"/orders/operate/{order_id}/settle",
        data={"subscription_id": offered.group(1)},
        follow_redirects=True,
    )
    assert settled.status_code == 200
    assert _order_state(order_id) == "settled"

    session = config.make_session("flask")
    try:
        order = orders_selectors.get_order(session, order_id)
        assert order is not None and order.invoice_id is not None, (
            "a settled order with no invoice is money nobody can account for"
        )
    finally:
        session.close()


def test_cancelling_a_reserved_order_gives_the_units_back() -> None:
    """(h) Reserve then cancel: `reserved` returns to exactly what it was, and the order stays.

    Exactly what it was, and not merely "lower": a release that gave back the wrong number leaves
    the shelf looking plausible while the warehouse refuses orders it could fill — the expensive
    kind of wrong, because `on_hand` is right the whole time and nothing looks broken.

    And the order is still THERE. A cancellation is a state, not a deletion: a customer asking why
    their order vanished is a question the database should be able to answer.
    """
    order_id, warehouse_id = _reservable_order()
    wanted = _wanted(order_id)
    before = _reserved_units(warehouse_id, [sku_id for sku_id, _ in wanted])

    client = app.test_client()
    assert (
        client.post(
            f"/orders/operate/{order_id}/reserve", follow_redirects=True
        ).status_code
        == 200
    )
    assert _reserved_units(warehouse_id, [sku_id for sku_id, _ in wanted]) != before

    cancelled = client.post(f"/orders/operate/{order_id}/cancel", follow_redirects=True)
    assert cancelled.status_code == 200
    assert _reserved_units(warehouse_id, [sku_id for sku_id, _ in wanted]) == before
    assert _order_state(order_id) == "cancelled"


def _an_invoice_of_the_customer(order_id: int) -> int:
    """An invoice the seeding already raised for that order's customer, in ONE statement.

    Read rather than created: `attach_invoice` is about billing against an invoice that ALREADY
    exists, and raising one here would test the operation against a fixture built for it. It also
    goes through the same two-hop selector the PAGE uses to fill its dropdown, so the test and the
    page agree about what a customer's invoices are.
    """
    session = config.make_session("flask")
    try:
        order = orders_selectors.get_order(session, order_id)
        assert order is not None, f"order {order_id} is gone"
        invoices = billing_usecases.invoices_of_customer(session, order.customer_id)
        assert invoices, "the seeding left that customer with no invoice"
        return invoices[0].id
    finally:
        session.close()


def test_billing_an_open_order_against_an_existing_invoice() -> None:
    """(h) The plain half of the joint with billing: it links the two rows and stops.

    No savepoint and no money moves. `settle` is the half that issues the invoice, charges and
    rewinds the shipment if the card is declined; this one bills against a bill that is already
    there, which is what a customer with an open account does every month.

    It was the last write the API could do and the pages could not, and closing it needed a selector
    before it needed a form: a page can only offer a choice it has a cheap way to list, and listing a
    customer's invoices per subscription is the N+1 that the very page it sits on argues against.
    """
    order_id, _ = _reservable_order(billable=True)
    invoice_id = _an_invoice_of_the_customer(order_id)

    client = app.test_client()
    billed = client.post(
        f"/orders/operate/{order_id}/attach",
        data={"invoice_id": invoice_id},
        follow_redirects=True,
    )

    assert billed.status_code == 200
    assert _order_state(order_id) == "invoiced"


def test_billing_against_an_invoice_that_is_not_there_is_a_404() -> None:
    """(h) A stale id from a form is a 404 from the use case, not an FK violation inside the commit.

    The invoice is looked up rather than trusted, which is the difference between a page that can
    say "that invoice is gone" and one that hands the reader a driver message.
    """
    order_id, _ = _reservable_order(billable=True)

    client = app.test_client()
    billed = client.post(
        f"/orders/operate/{order_id}/attach", data={"invoice_id": 999999}
    )

    assert billed.status_code == 404
    assert _order_state(order_id) == "draft"


def test_an_operation_that_is_not_offered_is_not_reachable() -> None:
    """(h) The page hides the button AND the operation refuses it: the rule is not in the template.

    Both halves matter, and only together. A page that hides a control it cannot honour is polite;
    an operation that refuses what its page hid is correct. Checking only the first would pass on a
    demo where the button is the entire enforcement, which is a domain whose rules live in HTML.

    A cancelled order is the case used because its refusal is the one with something to say: it has
    nothing left to reserve, and the state it is in has to survive being asked.
    """
    order_id = _order_in_state(OrderState.CANCELLED)
    client = app.test_client()

    page = client.get(f"/orders/operate/{order_id}").get_data(as_text=True)
    assert 'aria-disabled="true">Reserve the units</span>' in page
    assert (
        '<button class="btn btn-primary btn-md" type="submit">Reserve the units</button>'
        not in page
    )
    assert "Only a draft order can be reserved" in page, (
        "the page disabled the control without saying why"
    )

    refused = client.post(f"/orders/operate/{order_id}/reserve", follow_redirects=True)
    assert refused.status_code == 200
    assert "The reservation was refused" in refused.get_data(as_text=True)
    assert _order_state(order_id) == "cancelled"


def test_the_operations_are_handed_a_session_with_no_transaction() -> None:
    """(h) The `session.rollback()` in front of each operation is load-bearing, and this proves it.

    THE MISTAKE THIS CATCHES IS INVISIBLE WITHOUT IT. `reserve`, `settle` and `cancel_order` open by
    declaring `READ COMMITTED`, and `SET TRANSACTION ISOLATION LEVEL` is only valid as the first
    statement of a transaction — but Flask's app-wide `before_app_request` hook resolves
    `g.current_user` with a query on every request of the whole app, so by the time the handler runs
    the session can already be inside one. Postgres refuses the statement ONLY when it would change
    the level, and its default already IS `READ COMMITTED`: delete the rollback and nothing raises,
    nothing goes red, and the operation has silently stopped declaring its isolation and started
    inheriting it. MySQL's default is `REPEATABLE READ`, under which the losing customer dies with a
    driver serialisation error instead of being told `conflict`.

    So the test asks for the one thing the engine IS loud about: from inside the operation, a level
    the transaction does not already have. It raises `ActiveSqlTransaction` if anything read first
    and succeeds if nothing did — which is exactly the precondition, measured rather than asserted
    about the source.

    It logs in first, because that is what makes the hook query at all: signed out, `_current_user`
    reads a cookie and returns without touching the database, and the test would pass over a
    handler that has no rollback in it.
    """
    order_id, _ = _reservable_order()
    client = app.test_client()
    _login(client, "demo1", "test1234")

    complaints: list[str] = []
    unsupported: list[str] = []
    real = orders_usecases.reserve

    def probe(session: SnakeSession, *, order_id: int) -> Order | Failure:
        """Ask for a level this transaction does not have, then get out of the operation's way."""
        try:
            session.set_isolation(SnakeIsolation.SERIALIZABLE)
        except SnakeUnsupportedFeature as exc:
            # The engine cannot set a level AT ALL, so the probe measures nothing here. Kept apart
            # from `complaints` and turned into a skip below: counting it as a finding would fail
            # the demo on SQLite for a reason that has nothing to do with the rollback, and
            # swallowing it would report green over a check that never ran.
            unsupported.append(str(exc))
        except Exception as exc:  # noqa: BLE001  (any other refusal is the finding)
            complaints.append(f"{type(exc).__name__}: {exc}")
        session.rollback()
        return real(session, order_id=order_id)

    orders_usecases.reserve = probe
    try:
        reserved = client.post(
            f"/orders/operate/{order_id}/reserve", follow_redirects=True
        )
    finally:
        orders_usecases.reserve = real

    assert reserved.status_code == 200
    if unsupported:
        pytest.skip(f"this engine cannot set an isolation level: {unsupported[0]}")
    assert complaints == [], (
        "something read the database before the operation, so it could not declare its "
        f"isolation level: {complaints}"
    )
    assert _order_state(order_id) == "reserved", (
        "the probe did not reach the real operation"
    )


def test_the_sidebar_carries_orders_and_marks_it_current() -> None:
    """(h) The catalogue's `orders` section reaches the sidebar, operations link included.

    Three links and not two, and the third is the one the catalogue could not have routed on its
    own: `operate` carries no id, so the bare path has to mean the CHOOSER. That contract is written
    in `shared/web/nav.py` and reversed in `apps/nav.py`, and a missing entry there is a `KeyError`
    on EVERY page of the demo — which is precisely how this domain arrived.
    """
    client = app.test_client()
    body = client.get("/orders/list").get_data(as_text=True)

    assert 'href="/orders/list"' in body
    assert 'href="/orders/create"' in body
    assert 'href="/orders/operate"' in body
    assert '<a class="sidebar-link" href="/orders/list" aria-current="page">' in body

    chooser = client.get("/orders/operate").get_data(as_text=True)
    assert (
        '<a class="sidebar-link" href="/orders/operate" aria-current="page">' in chooser
    )
    assert (
        '<a class="sidebar-link" href="/orders/list" aria-current="page">'
        not in chooser
    )


# ---- (i) The reports, the exports and the billing pages ----------------------------------------


def _invoice_total(body: str) -> int:
    """How many invoices the billing pager claims there are, in TOTAL and not on the page shown."""
    found = re.search(r"· (\d+) invoice\(s\)", body)
    assert found is not None, "the page carries no pager to read a total off"
    return int(found.group(1))


def _csv_rows(body: str) -> list[str]:
    """The data lines of a CSV body, header dropped and the trailing blank line with it."""
    return [line for line in body.splitlines()[1:] if line]


def test_inventory_report_shows_the_figures_and_says_what_produced_them() -> None:
    """(i) The report renders REAL aggregates, and each table names the ORM feature behind it.

    Both halves are asserted because both are the point. A report that renders is a template that
    compiles; a report whose numbers are all zero is a page that queried nothing, and these demos are
    read as documentation, so a figure with no provenance next to it teaches nobody anything.
    """
    session = config.make_session("flask")
    try:
        warehouses = inventory_selectors.list_warehouses(session)
    finally:
        session.close()

    body = app.test_client().get("/inventory/report").get_data(as_text=True)

    for warehouse in warehouses:
        assert f">{warehouse.code}<" in body, (
            f"{warehouse.code} is missing from the roll call"
        )
    assert "annotate()" in body
    assert "having()" in body
    assert "window function" in body
    assert "SKUs that never moved" in body
    assert re.search(r"SKUs in the catalogue</dt>\s*<dd>[1-9]\d*</dd>", body), (
        "the catalogue count came back as zero: the report queried nothing"
    )


def test_orders_report_says_which_path_the_compound_took() -> None:
    """(i) The report renders, and it states whether the UNION ran as one statement or as two.

    `union_supported` is the one figure on that page that depends on the ENGINE rather than on the
    data — SQLite refuses parentheses around a compound's branches, so there the two branches run
    separately and are folded in Python. A demo that hid that would be hiding the most interesting
    thing on the page, so the assertion accepts either wording and demands one of them.
    """
    body = app.test_client().get("/orders/report").get_data(as_text=True)

    assert "annotate()" in body
    assert "having()" in body
    assert "window function" in body
    assert ("One UNION" in body) != ("Two statements" in body), (
        "the report does not say which path the compound took, or says both"
    )
    assert re.search(r'<td class="num">[1-9]\d*</td>', body), (
        "every figure on the report is zero: it queried nothing"
    )


def test_billing_list_paginates_and_the_paid_filter_narrows_it() -> None:
    """(i) The listing pages for real and `?paid=` cuts the total down, filter option still marked.

    The two open/settled totals are asserted to ADD UP to the unfiltered one, which is the check a
    filter that quietly did nothing would pass and a filter that dropped rows would not.
    """
    client = app.test_client()

    everything = client.get("/billing/list").get_data(as_text=True)
    settled = client.get("/billing/list?paid=paid").get_data(as_text=True)
    outstanding = client.get("/billing/list?paid=open").get_data(as_text=True)

    total = _invoice_total(everything)
    assert total > 0, "nothing was seeded, so the page proves nothing"
    assert _invoice_total(settled) + _invoice_total(outstanding) == total
    assert _invoice_total(outstanding) < total, "the filter narrowed nothing"
    assert 'value="open" selected' in outstanding, (
        "the filter forgot which option it is on"
    )
    assert 'class="pager"' in everything
    assert (
        '<span class="btn btn-ghost btn-md" aria-disabled="true">Previous</span>'
        in everything
    )

    first = set(re.findall(r"/billing/detail/(\d+)", everything))
    second = set(
        re.findall(
            r"/billing/detail/(\d+)",
            client.get("/billing/list?page=2").get_data(as_text=True),
        )
    )
    assert first and second
    assert not (first & second), "both pages show the same invoices"


def test_billing_detail_shows_an_invoice_and_a_bad_id_is_a_404() -> None:
    """(i) The detail resolves the three to-one hops, and an id nobody holds answers 404."""
    client = app.test_client()
    listing = client.get("/billing/list").get_data(as_text=True)
    ids = re.findall(r"/billing/detail/(\d+)", listing)
    assert ids, "the listing linked to no invoice at all"

    found = client.get(f"/billing/detail/{ids[0]}")
    body = found.get_data(as_text=True)
    assert found.status_code == 200
    assert "Outstanding" in body and "Collected" in body
    assert "Payments" in body

    assert client.get("/billing/detail/999999").status_code == 404


def test_billing_report_shows_the_plans_and_what_they_earned() -> None:
    """(i) The money report renders both tables with real rows, and names the gap between them."""
    session = config.make_session("flask")
    try:
        plans = billing_selectors.list_plans(session)
    finally:
        session.close()

    body = app.test_client().get("/billing/report").get_data(as_text=True)

    assert plans, "no plans were seeded, so the page proves nothing"
    for plan in plans:
        assert f">{plan.name}<" in body, f"{plan.name} is missing from the roll call"
    assert "annotate()" in body
    assert "having()" in body
    assert "Plans with subscribers and no revenue" in body
    assert "Unpaid invoices" in body


def test_the_movements_export_is_a_csv_download_with_real_rows() -> None:
    """(i) `text/csv`, the view model's own filename, a header line and data under it.

    The header is compared to the constant the view model publishes rather than to a list retyped
    here: two spellings of the same columns is exactly the drift the view-model layer exists to stop.
    """
    response = app.test_client().get("/inventory/export")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert (
        response.headers["Content-Disposition"]
        == 'attachment; filename="stock-movements.csv"'
    )
    assert body.splitlines()[0] == ",".join(inventory_viewmodels.MOVEMENT_EXPORT_HEADER)
    rows = _csv_rows(body)
    assert rows, "the file has a header and nothing under it"
    for row in rows:
        assert len(row.split(",")) >= len(inventory_viewmodels.MOVEMENT_EXPORT_HEADER)

    narrowed = _csv_rows(
        app.test_client().get("/inventory/export?warehouse=1").get_data(as_text=True)
    )
    assert 0 < len(narrowed) < len(rows), "?warehouse= narrowed nothing"


def test_the_order_lines_export_is_a_csv_download_with_real_rows() -> None:
    """(i) The second export obeys the same contract over its own table and its own filter.

    Said twice on purpose, once per export. They are separate code paths over separate tables, and a
    single shared assertion is what would let one of them break while the other kept the check green.
    """
    response = app.test_client().get("/orders/export")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert (
        response.headers["Content-Disposition"]
        == 'attachment; filename="order-lines.csv"'
    )
    assert body.splitlines()[0] == ",".join(orders_viewmodels.LINE_EXPORT_HEADER)
    rows = _csv_rows(body)
    assert rows, "the file has a header and nothing under it"

    drafts = _csv_rows(
        app.test_client().get("/orders/export?state=draft").get_data(as_text=True)
    )
    assert 0 < len(drafts) < len(rows), "?state= narrowed nothing"
    for row in drafts:
        assert ",draft," in row, f"a non-draft line survived the filter: {row}"


def test_the_export_response_streams_and_reads_only_what_is_asked_for() -> None:
    """(i) THE export test: the HANDLER streams, measured on the driver from outside it.

    `shared/tests/test_exports_stream.py` already proves the VIEW MODEL is lazy, and that is exactly
    why this one exists: a `list()` written in the route would leave every one of those assertions
    green while the page went back to building the whole file in memory. So this reads the response
    the route actually returns, four lines out of a table with hundreds in it, and asks the driver
    what the cursor consumed. Three rows read, three rows recorded.

    It calls the view UNDER the WSGI middleware and not through the test client, and that is not a
    shortcut. `SnakeDebugWSGI` joins the whole body with `b"".join(...)` so it can time the request
    and inject the panel, so through the client every response is materialised no matter how it was
    produced. What the middleware cannot change is the shape of the EXECUTION, which is what is
    measured here.
    """
    with app.test_request_context("/inventory/export"):
        app.preprocess_request()
        response = inventory_urls.export_movements()
        assert isinstance(response, Response)
        assert response.is_streamed, "the route handed back a body of known length"

        with capture_queries() as collector:
            stream = iter(response.response)
            lines = [next(stream) for _ in range(4)]
            # The record lands when the cursor is torn down, so the close belongs INSIDE the scope.
            response.close()

    report = collector.report()
    # A streamed body is `Iterable[str] | Iterable[bytes]`, and this exporter yields text; decoding
    # the other half keeps the assertion true for both instead of true for the one we happen to get.
    head = lines[0]
    assert (head.decode() if isinstance(head, bytes) else head).startswith(
        "movement_id,"
    )
    assert report.count == 1, report.to_text()
    assert report.records[0].rows == 3, (
        f"the cursor consumed {report.records[0].rows} rows for a three-row read: the route "
        f"materialised the export instead of streaming it."
    )


def test_the_streamed_export_outlives_the_request_teardown() -> None:
    """(i) The body is produced AFTER the view returns, and it still has a live session to read from.

    This is the classic failure of a streaming export and it is not hypothetical here: the request's
    session is closed by a `teardown_app_request` hook, Flask pops the request context as soon as it
    has the response object, and the first row is asked for after that. [measured] The documented
    cure does NOT cure it — on Flask 3.1 `stream_with_context` pushes its contexts lazily, so the
    teardown has already run by the time the body is pulled, and the export dies with
    `psycopg2.InterfaceError: connection already closed`. `apps/exports.py` takes the session off `g`
    instead, which leaves the hook nothing to close and hands ownership to the stream.

    What pins it is a full round trip that comes back with DATA in it. A closed session cannot open a
    cursor, so rows in the body are the proof; a status code alone would not be, since the header line
    is written before the query has run at all.
    """
    response = app.test_client().get("/inventory/export")
    rows = _csv_rows(response.get_data(as_text=True))

    assert response.status_code == 200
    assert len(rows) > 10, (
        "the download came back with a header and (almost) nothing else: the session was closed "
        "before the body was produced."
    )


def test_the_sidebar_carries_the_reports_the_exports_and_billing() -> None:
    """(i) The six pages phase 4 added to the catalogue are six links this demo can reverse.

    A missing entry in `apps/nav.py` is not a broken link, it is a `KeyError` on EVERY page of the
    demo: the sidebar is built by an app-wide context processor. `shared/tests/test_nav_is_wired_in_
    both_demos.py` guards the map by reading the source; this one guards the rendering, which is the
    half that catches an endpoint that exists in the dict and nowhere else.
    """
    body = app.test_client().get("/billing/list").get_data(as_text=True)

    for href in (
        "/inventory/report",
        "/inventory/export",
        "/orders/report",
        "/orders/export",
        "/billing/list",
        "/billing/report",
    ):
        assert f'href="{href}"' in body, f"the sidebar has no link to {href}"
    assert '<a class="sidebar-link" href="/billing/list" aria-current="page">' in body
    assert "/billing/create" not in body, (
        "billing grew a creation link: the domain has no writes, and the catalogue says so"
    )


def _main() -> int:
    """pytest-less runner: it runs the checks and returns the exit code."""
    checks = [
        ("auth + SSR CRUD flow", test_auth_and_post_crud_roundtrip),
        ("cannot edit other people's posts (404)", test_cannot_edit_others_posts),
        ("(a) SSR panel injected", test_ssr_panel_is_injected),
        ("(b) snakeorm envelope + Server-Timing", test_api_envelope_and_server_timing),
        ("(d) OpenAPI at /api/openapi.json", test_openapi_spec_is_served),
        ("(e) Swagger UI at /api/docs", test_swagger_ui_is_served),
        ("(c) include with NO N+1 (1 query)", test_include_has_no_n_plus_one),
        (
            "(f) inventory CRUD over the composite key",
            test_inventory_crud_over_the_composite_key,
        ),
        (
            "(g) inventory listing + pager",
            test_inventory_list_renders_its_rows_and_a_real_pager,
        ),
        (
            "(g) inventory warehouse filter",
            test_inventory_filter_narrows_the_listing_to_one_warehouse,
        ),
        ("(g) inventory page 2 != page 1", test_inventory_page_two_is_not_page_one),
        (
            "(g) inventory detail + 404 on a bad pair",
            test_inventory_detail_shows_a_pair_and_a_bad_pair_is_a_404,
        ),
        (
            "(g) inventory create round trip",
            test_inventory_create_round_trips_to_the_database,
        ),
        (
            "(g) inventory update of the levels",
            test_inventory_update_changes_the_levels,
        ),
        (
            "(g) inventory delete refused (FK restrict)",
            test_inventory_delete_is_refused_when_it_would_orphan_the_history,
        ),
        (
            "(g) sidebar on every page, current marked",
            test_the_sidebar_is_on_every_page_and_marks_the_one_you_are_on,
        ),
        (
            "(h) orders listing + pager",
            test_orders_list_renders_its_rows_and_a_real_pager,
        ),
        ("(h) orders state filter", test_orders_state_filter_narrows_the_listing),
        (
            "(h) orders detail + 404 on a bad id",
            test_orders_detail_shows_an_order_and_a_bad_id_is_a_404,
        ),
        (
            "(h) orders create round trip",
            test_orders_create_round_trips_to_the_database,
        ),
        (
            "(h) reserve holds the units (row lock)",
            test_reserve_holds_the_units_on_the_real_stock_row,
        ),
        (
            "(h) settle reaches SETTLED with an invoice",
            test_settle_bills_a_reserved_order_and_takes_it_to_settled,
        ),
        (
            "(h) cancel gives the units back",
            test_cancelling_a_reserved_order_gives_the_units_back,
        ),
        (
            "(h) an operation not offered is not reachable",
            test_an_operation_that_is_not_offered_is_not_reachable,
        ),
        (
            "(h) the operations get a session with no transaction",
            test_the_operations_are_handed_a_session_with_no_transaction,
        ),
        (
            "(h) sidebar carries orders, chooser marked",
            test_the_sidebar_carries_orders_and_marks_it_current,
        ),
        (
            "(i) inventory report: figures + provenance",
            test_inventory_report_shows_the_figures_and_says_what_produced_them,
        ),
        (
            "(i) orders report says which UNION path ran",
            test_orders_report_says_which_path_the_compound_took,
        ),
        (
            "(i) billing listing: pager + paid filter",
            test_billing_list_paginates_and_the_paid_filter_narrows_it,
        ),
        (
            "(i) billing detail + 404 on a bad id",
            test_billing_detail_shows_an_invoice_and_a_bad_id_is_a_404,
        ),
        (
            "(i) billing report: plans + revenue + gap",
            test_billing_report_shows_the_plans_and_what_they_earned,
        ),
        (
            "(i) movements export is a real CSV download",
            test_the_movements_export_is_a_csv_download_with_real_rows,
        ),
        (
            "(i) order lines export is a real CSV download",
            test_the_order_lines_export_is_a_csv_download_with_real_rows,
        ),
        (
            "(i) the export STREAMS (3 read, 3 consumed)",
            test_the_export_response_streams_and_reads_only_what_is_asked_for,
        ),
        (
            "(i) the stream outlives the request teardown",
            test_the_streamed_export_outlives_the_request_teardown,
        ),
        (
            "(i) sidebar carries reports, exports and billing",
            test_the_sidebar_carries_the_reports_the_exports_and_billing,
        ),
    ]
    failures = 0
    for label, check in checks:
        reset_and_seed()
        try:
            check()
        except Exception as exc:  # noqa: BLE001  (demo runner: report and carry on)
            failures += 1
            print(f"  FAIL   {label}: {exc}")
        else:
            print(f"  OK     {label}")
    print()
    if failures:
        print(f"RESULT: {failures} check(s) FAILED")
        return 1
    print("RESULT: EVERYTHING PASSES")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
