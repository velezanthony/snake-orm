"""The inventory report's warehouse totals can be re-read with `fetch`, and the page works without it.

The twin of `flask/test_the_warehouse_totals_refresh_without_reloading.py`, and it exists for the
same reason every mirrored net in `frameworks/` does: a behaviour that only one of the two SSR demos
has is a reader concluding the ORM cannot do it in theirs.

The `snakeorm` block is asserted here separately rather than trusted from the Flask run, because the
`envelope` channel is configured per demo — `config/settings.py` has its own `SNAKE_ORM_DEBUG` — and
one demo shipping the report inside its JSON while the other does not is exactly the kind of
difference that never shows up until somebody opens the network tab.

`SimpleTestCase`: the rows are SnakeORM's, and Django's ORM holds none of this.
"""

from __future__ import annotations

import json
from typing import Literal

from django.test import Client, SimpleTestCase, override_settings

from apps.blog import seed

# Django keeps its trailing slash ON PURPOSE (`APPEND_SLASH` is the framework convention), so the
# same page is `/inventory/report/` here and `/inventory/report` in the Flask twin. Written out
# rather than reversed, because the slash is half of what this pair of files is comparing.
_REPORT = "/inventory/report/"
_ENDPOINT = "/api/inventory/stats"


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"])
class WarehouseTotalsRefreshTests(SimpleTestCase):
    """The markup the refresh needs, and the JSON it reads."""

    databases: set[str] | Literal["__all__"] = set()

    @classmethod
    def setUpClass(cls) -> None:
        """Seeds once: nothing in this file writes."""
        super().setUpClass()
        seed.reset_and_seed()

    def setUp(self) -> None:
        """A client per test."""
        self.client = Client()

    def test_the_report_already_holds_the_figures(self) -> None:
        """Server-rendered, with the id the refresh repaints. Whole before any script runs."""
        body = self.client.get(_REPORT).content.decode()

        self.assertIn('<tbody id="warehouse-totals">', body)
        self.assertIn("What each warehouse holds", body)

    def test_the_control_is_hidden_until_javascript_shows_it(self) -> None:
        """`hidden` in the markup, revealed by `demo.js`. With scripts off there is no dead button."""
        body = self.client.get(_REPORT).content.decode()

        self.assertIn("data-needs-js hidden", body)

    def test_the_button_points_at_the_endpoint_and_the_table(self) -> None:
        """The three data attributes `snakeRefreshWarehouses` reads are there and all resolve."""
        body = self.client.get(_REPORT).content.decode()

        self.assertIn(f'data-endpoint="{_ENDPOINT}"', body)
        self.assertIn('data-target="warehouse-totals"', body)
        self.assertIn('data-status="warehouse-totals-status"', body)
        self.assertIn('id="warehouse-totals-status"', body)

    def test_the_endpoint_answers_what_the_script_paints(self) -> None:
        """Four fields per row, and the two that are nested are nested where `demo.js` looks."""
        response = self.client.get(_ENDPOINT)
        payload = json.loads(response.content)
        rows = payload["data"]

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            rows, "no warehouses: the assertions below would hold over an empty list"
        )
        self.assertGreaterEqual(set(rows[0]), {"warehouse", "sku_count", "total_units"})
        self.assertGreaterEqual(set(rows[0]["warehouse"]), {"code", "name"})

    def test_the_report_rides_inside_the_body(self) -> None:
        """The `snakeorm` block travels in the JSON, which is the point of calling it with `fetch`.

        On an ARRAY the envelope wraps the answer as `{data, snakeorm}` — the reason `demo.js` reads
        `payload.data` before falling back to the payload itself. Without this key there would be
        nothing for the debug history to read out of a JSON call.
        """
        payload = json.loads(self.client.get(_ENDPOINT).content)

        self.assertIn(
            "snakeorm",
            payload,
            "the envelope channel is off: the JSON carries no report",
        )
        self.assertIn("summary", payload["snakeorm"])
        self.assertIn("queries", payload["snakeorm"])
