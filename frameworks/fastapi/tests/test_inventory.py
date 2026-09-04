"""The inventory endpoints over HTTP: the wrapper is thin, and this is what proves it.

The logic lives in `shared` and the shared suite already pins it. What is checked HERE is the part
only the framework can get wrong: that the routes carry BOTH halves of the composite key, that a
`Failure` becomes the status its reason maps to, and that the types survive the JSON — a price as
exact TEXT, a UUID as text, a thumbnail as a size and not as a payload.

The whole flow is one shipment's worth of an inventory: create a SKU, receive it, try to ship more
than there is, ship what there is, count, reserve, and read it back with its movements.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ["SNAKE_ORM_DEBUG"] = "envelope,timing,sidecar"

from fastapi.testclient import TestClient  # noqa: E402
from httpx import Response  # noqa: E402

from main import app  # noqa: E402


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """A client with the lifecycle active: the schema is migrated and seeded on startup."""
    with TestClient(app) as test_client:
        yield test_client


def _rows(response: Response) -> list[dict[str, object]]:
    """The list out of a response. With the `envelope` channel on, an ARRAY travels under `data`.

    A list has nowhere to hang a key, so the debug block wraps it instead of adding a sibling. The
    test switches that channel on itself, so unwrapping here is reading the product, not working
    around it.

    The parameter used to be `object` with a `# type: ignore[attr-defined]` on `.json()` — `object`
    says "I know nothing about this" and the ignore then says "check nothing either", which is a
    strange pair of promises to make about the value every assertion below depends on.
    """
    payload = response.json()
    rows = payload["data"] if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise AssertionError(f"expected a JSON array, got {type(rows).__name__}")
    return [row for row in rows if isinstance(row, dict)]


def _int(value: object) -> int:
    """A number read out of a JSON body — converted where it is read, not assumed at every use."""
    if not isinstance(value, int):
        raise AssertionError(f"expected a number, got {type(value).__name__}")
    return value


def _text(value: object) -> str:
    """Text read out of a JSON body."""
    if not isinstance(value, str):
        raise AssertionError(f"expected text, got {type(value).__name__}")
    return value


def _nested(value: object) -> list[dict[str, object]]:
    """A nested JSON array of objects, such as the movements hanging off a stock row."""
    if not isinstance(value, list):
        raise AssertionError(f"expected a JSON array, got {type(value).__name__}")
    return [item for item in value if isinstance(item, dict)]


def _object(value: object) -> dict[str, object]:
    """A nested JSON object, such as the warehouse hanging off a stats row."""
    if not isinstance(value, dict):
        raise AssertionError(f"expected a JSON object, got {type(value).__name__}")
    return value


def _first_warehouse_id(client: TestClient) -> int:
    warehouses = _rows(client.get("/api/inventory/warehouses"))
    assert warehouses, (
        "the seeding left no warehouses: the test would be measuring the void"
    )
    return _int(warehouses[0]["id"])


def _new_sku_id(client: TestClient) -> int:
    created = client.post(
        "/api/inventory/skus",
        json={
            "name": "Test widget",
            "kind": "physical",
            "price": "12.34",
            "weight_kg": 1.5,
            "lead_time_days": 2,
            "attrs": {"colour": "blue"},
            "related_ids": [1, 2],
        },
    )
    assert created.status_code == 201, created.text
    return int(created.json()["id"])


def test_the_price_travels_exact_and_the_thumbnail_does_not_travel(
    client: TestClient,
) -> None:
    """A `Decimal` goes out as TEXT so the cent survives, and `bytes` goes out as a SIZE."""
    sku_id = _new_sku_id(client)

    sku = next(s for s in _rows(client.get("/api/inventory/skus")) if s["id"] == sku_id)

    assert sku["price"] == "12.34"
    assert sku["attrs"] == {"colour": "blue"}
    assert sku["related_ids"] == [1, 2]
    assert sku["thumbnail_bytes"] == 0
    assert len(_text(sku["public_id"])) == 36


def test_a_stock_row_is_addressed_by_both_halves_of_its_key(
    client: TestClient,
) -> None:
    """The route carries warehouse AND sku, because neither identifies the row on its own."""
    warehouse_id, sku_id = _first_warehouse_id(client), _new_sku_id(client)

    received = client.post(
        f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}/receive",
        json={"units": 10},
    )

    assert received.status_code == 200, received.text
    assert received.json()["warehouse_id"] == warehouse_id
    assert received.json()["sku_id"] == sku_id
    assert received.json()["on_hand"] == 10


def test_shipping_more_than_there_is_answers_409_and_writes_nothing(
    client: TestClient,
) -> None:
    """The reason `conflict` maps to 409, and the refusal happens before anything is written."""
    warehouse_id, sku_id = _first_warehouse_id(client), _new_sku_id(client)
    client.post(
        f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}/receive",
        json={"units": 4},
    )

    refused = client.post(
        f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}/ship",
        json={"units": 9},
    )

    assert refused.status_code == 409
    movements = _rows(
        client.get(f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}/movements")
    )
    assert [m["delta"] for m in movements] == [4]


def test_a_count_upserts_and_a_reserve_touches_every_row(client: TestClient) -> None:
    """The count sets the pair whether or not it was there; the reserve is ONE statement."""
    warehouse_id, sku_id = _first_warehouse_id(client), _new_sku_id(client)

    counted = client.put(
        f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}",
        json={"on_hand": 25},
    )
    reserved = client.post(
        f"/api/inventory/warehouses/{warehouse_id}/reserve", json={"units": 1}
    )

    assert counted.status_code == 200, counted.text
    assert reserved.json()["rows"] >= 1
    rows = _rows(client.get(f"/api/inventory/warehouses/{warehouse_id}/stock"))
    mine = next(row for row in rows if row["sku_id"] == sku_id)
    assert mine["on_hand"] == 25
    assert mine["available"] == _int(mine["on_hand"]) - _int(mine["reserved"])


def test_the_movements_come_nested_under_their_stock_row(client: TestClient) -> None:
    """The to-many over a COMPOSITE foreign key, served as JSON."""
    warehouse_id, sku_id = _first_warehouse_id(client), _new_sku_id(client)
    client.post(
        f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}/receive",
        json={"units": 6},
    )

    rows = _rows(
        client.get(f"/api/inventory/warehouses/{warehouse_id}/stock/movements")
    )

    mine = next(row for row in rows if row["sku_id"] == sku_id)
    assert [m["delta"] for m in _nested(mine["movements"])] == [6]
    assert all("movements" in row for row in rows)


def test_the_stats_come_aggregated_per_warehouse(client: TestClient) -> None:
    """`annotate` gives back the warehouse plus its aggregates, with no query per row."""
    stats = _rows(client.get("/api/inventory/stats"))

    assert stats, "the seeding left no warehouses"
    assert all("sku_count" in s and "total_units" in s for s in stats)
    assert all(_object(s["warehouse"])["code"] for s in stats)


def test_an_unknown_warehouse_answers_404(client: TestClient) -> None:
    """`not_found` maps to 404, and asking for stock of nothing is not an empty list."""
    assert client.get("/api/inventory/warehouses/999999").status_code == 404
    assert client.get("/api/inventory/warehouses/999999/stock").status_code == 404


def test_a_patch_corrects_both_levels_and_a_missing_pair_is_a_404(
    client: TestClient,
) -> None:
    """`PATCH` edits a pair that exists, and refuses to invent one that does not.

    That is the whole difference from the `PUT` above, and it is why they are two verbs on one path
    rather than one endpoint with a flag: an upsert means "this pair now holds N whether or not it
    was there", and a correction means "the row somebody opened now says this". A pair that vanished
    between the form being drawn and being submitted is a 404, not a silent insert.
    """
    warehouse_id, sku_id = _first_warehouse_id(client), _new_sku_id(client)
    client.put(
        f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}", json={"on_hand": 30}
    )

    corrected = client.patch(
        f"/api/inventory/warehouses/{warehouse_id}/stock/{sku_id}",
        json={"on_hand": 30, "reserved": 4},
    )
    missing = client.patch(
        f"/api/inventory/warehouses/{warehouse_id}/stock/999999",
        json={"on_hand": 1, "reserved": 0},
    )

    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["reserved"] == 4
    assert missing.status_code == 404


def test_a_delete_removes_an_untouched_pair_and_refuses_one_with_history(
    client: TestClient,
) -> None:
    """204 for a pair nobody moved, 409 for one that has movements.

    The 409 is the interesting half and the same answer the delete PAGE gives: the movements are the
    audit trail and the foreign key is RESTRICT, so a pair that has moved gets closed rather than
    deleted. Without this check the engine refuses three layers down, inside a commit, with a driver
    error nobody can turn into a page.
    """
    warehouse_id = _first_warehouse_id(client)
    untouched, moved = _new_sku_id(client), _new_sku_id(client)
    client.put(
        f"/api/inventory/warehouses/{warehouse_id}/stock/{untouched}",
        json={"on_hand": 5},
    )
    client.post(
        f"/api/inventory/warehouses/{warehouse_id}/stock/{moved}/receive",
        json={"units": 5},
    )

    removed = client.delete(
        f"/api/inventory/warehouses/{warehouse_id}/stock/{untouched}"
    )
    refused = client.delete(f"/api/inventory/warehouses/{warehouse_id}/stock/{moved}")

    assert removed.status_code == 204, removed.text
    assert refused.status_code == 409, refused.text
