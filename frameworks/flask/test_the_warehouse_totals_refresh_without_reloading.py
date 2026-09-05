"""The inventory report's warehouse totals can be re-read with `fetch`, and the page works without it.

WHY THIS PAGE AND THIS TABLE. "What each warehouse holds" is an operational figure that goes stale
while you look at it: the receive, ship and reserve pages next door move those units, and the report
is where somebody watches the result. So a re-read is what a reader would want here anyway — the
button is not a place to hang a demonstration.

WHY IT IS AN ENHANCEMENT AND NOT A FEATURE. The server has already rendered those rows. With scripts
off the page is complete and the control is not even shown (`data-needs-js` + `hidden`), so nothing
is offered that cannot be done. A button that a reader can press and that does nothing is worse than
no button, and it is what "progressive enhancement" turns into when nobody checks.

WHAT IT PROVES ABOUT THE ORM, which is why the endpoint matters as much as the markup. This is the
JSON half of the debug report: `/api/inventory/stats` answers `application/json`, so the report rides
INSIDE the body under `snakeorm` (the `envelope` channel) instead of in the headers the way the HTML
fragment on the lab's pager does. That is also why a list endpoint answers `{data, snakeorm}` rather
than a bare array, and the shape is asserted here because `demo.js` reads it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient

from app import create_app

app = create_app()

_REPORT = "/inventory/report"
_ENDPOINT = "/api/inventory/stats"


@pytest.fixture(scope="module")
def client() -> Iterator[FlaskClient]:
    """One client for the whole file: nothing here writes."""
    with app.test_client() as test_client:
        yield test_client


def test_the_report_already_holds_the_figures(client: FlaskClient) -> None:
    """Server-rendered, with the id the refresh repaints. The page is whole before any script runs."""
    body = client.get(_REPORT).get_data(as_text=True)

    assert '<tbody id="warehouse-totals">' in body
    assert "What each warehouse holds" in body


def test_the_control_is_hidden_until_javascript_shows_it(client: FlaskClient) -> None:
    """`hidden` in the markup, revealed by `demo.js`. With scripts off there is no dead button."""
    body = client.get(_REPORT).get_data(as_text=True)

    assert "data-needs-js hidden" in body


def test_the_button_points_at_the_endpoint_and_the_table(client: FlaskClient) -> None:
    """The three data attributes `snakeRefreshWarehouses` reads are all there and all resolve."""
    body = client.get(_REPORT).get_data(as_text=True)

    assert f'data-endpoint="{_ENDPOINT}"' in body
    assert 'data-target="warehouse-totals"' in body
    assert 'data-status="warehouse-totals-status"' in body
    assert 'id="warehouse-totals-status"' in body


def test_the_endpoint_answers_what_the_script_paints(client: FlaskClient) -> None:
    """Four fields per row, and the two that are nested are nested where `demo.js` looks."""
    response = client.get(_ENDPOINT)
    payload = json.loads(response.get_data(as_text=True))
    rows = payload["data"]

    assert response.status_code == 200
    assert rows, "no warehouses: the assertions below would hold over an empty list"
    first = rows[0]
    assert set(first) >= {"warehouse", "sku_count", "total_units"}
    assert set(first["warehouse"]) >= {"code", "name"}


def test_the_report_rides_inside_the_body(client: FlaskClient) -> None:
    """The `snakeorm` block travels in the JSON, which is the whole point of calling it with `fetch`.

    On an ARRAY the envelope wraps the answer as `{data, snakeorm}` — the reason `demo.js` reads
    `payload.data` before falling back to the payload itself. Without this key there would be nothing
    for the debug history to read out of a JSON call, and the button would be exercising nothing.
    """
    payload = json.loads(client.get(_ENDPOINT).get_data(as_text=True))

    assert "snakeorm" in payload, (
        "the envelope channel is off: the JSON carries no report"
    )
    assert "summary" in payload["snakeorm"]
    assert "queries" in payload["snakeorm"]
