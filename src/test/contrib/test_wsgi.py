"""The WSGI adapter (Flask), tested over PURE WSGI —without installing Flask—.

A WSGI app is `callable(environ, start_response) -> Iterable[bytes]`, so it is exercised with a fake
app and a `start_response` that collects status and headers.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any

from snakeorm.contrib.wsgi import SnakeDebugWSGI
from snakeorm.debug import CaptureDriver, SnakeDebugChannel, SnakeDebugConfig


class _Inner:
    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields whatever
        `fetch_all` returns. The degradation is written HERE, in plain sight, not done by the framework."""
        yield from self.fetch_all(sql, params)

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        return [(1,)]

    def execute(self, sql: str, params: Sequence[object]) -> int:
        return 1

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


def _json_app(
    driver: CaptureDriver, body: bytes = b'{"id":7}'
) -> Callable[[dict[str, str], Callable[..., object]], Iterable[bytes]]:
    """Fake WSGI app: it runs a query and returns a JSON."""

    def app(
        environ: dict[str, str], start_response: Callable[..., object]
    ) -> Iterable[bytes]:
        driver.fetch_all("SELECT 1", ())
        start_response("200 OK", [("Content-Type", "application/json")])
        return [body]

    return app


def _run(
    middleware: SnakeDebugWSGI, environ: dict[str, str]
) -> tuple[dict[str, Any], bytes]:
    """Runs the middleware and returns (captured status+headers, body)."""
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> object:
        captured["status"] = status
        captured["headers"] = headers
        return None

    body = b"".join(middleware(environ, start_response))
    return captured, body


def test_envelope_injected_into_json_with_trigger() -> None:
    """With the `envelope` channel and `?_debug=1`, the JSON comes back with a `snakeorm` block."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugWSGI(
        _json_app(driver),
        channels=frozenset({SnakeDebugChannel.ENVELOPE}),
        production=False,
    )
    _, body = _run(mw, {"PATH_INFO": "/x", "QUERY_STRING": "_debug=1"})
    data = json.loads(body)
    assert data["id"] == 7
    assert data["snakeorm"]["count"] == 1


def test_timing_header_added() -> None:
    """The `timing` channel adds the Server-Timing header."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugWSGI(
        _json_app(driver),
        channels=frozenset({SnakeDebugChannel.TIMING}),
        production=False,
    )
    captured, _ = _run(mw, {"PATH_INFO": "/x", "QUERY_STRING": ""})
    names = {key.lower() for key, _ in captured["headers"]}
    assert "server-timing" in names


def test_sidecar_serves_the_panel_page() -> None:
    """With `sidecar`, the response carries a token and `/__snake__/{token}` serves the HTML panel."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugWSGI(
        _json_app(driver),
        channels=frozenset({SnakeDebugChannel.SIDECAR}),
        production=False,
    )
    captured, _ = _run(mw, {"PATH_INFO": "/x", "QUERY_STRING": ""})
    token = next(
        value for key, value in captured["headers"] if key.lower() == "x-debug-token"
    )
    _, page = _run(mw, {"PATH_INFO": f"/__snake__/{token}", "QUERY_STRING": ""})
    assert b"snake-debug-panel" in page


def _html_app(
    driver: CaptureDriver,
) -> Callable[[dict[str, str], Callable[..., object]], Iterable[bytes]]:
    """Fake WSGI app: it runs a query and returns an HTML page."""

    def app(
        environ: dict[str, str], start_response: Callable[..., object]
    ) -> Iterable[bytes]:
        driver.fetch_all("SELECT 1", ())
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [b"<html><body><h1>hi</h1></body></html>"]

    return app


def test_ssr_panel_carries_the_configured_csp_nonce() -> None:
    """The `csp_nonce` of `SnakeDebugConfig` reaches the panel delivered by the middleware.

    Without it, an app with a strict CSP gets the panel blocked by the browser and no error
    anywhere: the config was declared and the adapter dropped it on the floor.
    """
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugWSGI(
        _html_app(driver),
        channels=frozenset({SnakeDebugChannel.SSR}),
        config=SnakeDebugConfig(csp_nonce="r4nd0m"),
        production=False,
    )
    _, body = _run(mw, {"PATH_INFO": "/x", "QUERY_STRING": ""})
    assert b'<script type="module" nonce="r4nd0m">' in body


def test_ssr_panel_without_a_nonce_is_unchanged() -> None:
    """With no nonce configured, the delivered HTML carries no nonce at all (output unchanged)."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugWSGI(
        _html_app(driver),
        channels=frozenset({SnakeDebugChannel.SSR}),
        config=SnakeDebugConfig(),
        production=False,
    )
    _, body = _run(mw, {"PATH_INFO": "/x", "QUERY_STRING": ""})
    assert b"snake-debug-panel" in body
    assert b"nonce" not in body


def _fragment_app(
    driver: CaptureDriver,
) -> Callable[[dict[str, str], Callable[..., object]], Iterable[bytes]]:
    """Fake WSGI app: it runs a query and returns an HTML FRAGMENT (no `</body>`)."""

    def app(
        environ: dict[str, str], start_response: Callable[..., object]
    ) -> Iterable[bytes]:
        driver.fetch_all("SELECT 1", ())
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [b'<li class="row">7</li>']

    return app


def test_a_fragment_keeps_its_body_and_gets_the_headers() -> None:
    """An HTMX-style fragment comes back byte for byte, and its debug rides in the headers.

    The whole middleware is exercised, not just the pure layer: SSR is on and the response is
    `text/html`, which is precisely the combination that used to append the entire panel to a
    fragment about to be swapped into a live page.
    """
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugWSGI(
        _fragment_app(driver),
        channels=frozenset(
            {
                SnakeDebugChannel.SSR,
                SnakeDebugChannel.TIMING,
                SnakeDebugChannel.SIDECAR,
            }
        ),
        production=False,
    )

    captured, body = _run(mw, {"PATH_INFO": "/rows", "QUERY_STRING": ""})

    assert body == b'<li class="row">7</li>'
    names = {key.lower() for key, _ in captured["headers"]}
    assert "server-timing" in names
    assert "x-debug-token" in names


def test_the_report_names_the_request_it_came_from() -> None:
    """The WSGI adapter fills the identity: verb, path, status and the instant it started.

    `PATH_INFO` was already read and the status already captured; `REQUEST_METHOD` was the one piece
    the adapter had in `environ` and never looked at.
    """
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugWSGI(
        _json_app(driver),
        channels=frozenset({SnakeDebugChannel.ENVELOPE}),
        production=False,
    )

    _, body = _run(
        mw, {"PATH_INFO": "/users/7", "QUERY_STRING": "", "REQUEST_METHOD": "POST"}
    )

    request = json.loads(body)["snakeorm"]["request"]
    assert request["method"] == "POST"
    assert request["path"] == "/users/7"
    assert request["status"] == 200
    assert request["at"]  # the instant, measured where `wall_ms` is


def test_the_panel_does_not_reach_an_html_response_in_production() -> None:
    """`ssr` configured + `production=True` = no panel. End to end, through the middleware.

    The unit test on `allowed_channels` checks the set arithmetic; this one checks that the gate is
    actually WIRED to the path that injects. They are different failures: `ssr` used to survive the
    production filter, and `transform_body` injects on nothing more than `SSR in channels` and a
    `text/html` content type — no token, no header, no second guard. So a plain `GET /` from an
    anonymous visitor came back with every statement of the request, the placeholders already
    replaced by their values, and the `file:line` of the code that fired them.
    """
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugWSGI(
        _html_app(driver),
        channels=frozenset({SnakeDebugChannel.SSR}),
        production=True,
    )

    _, body = _run(mw, {"PATH_INFO": "/x", "QUERY_STRING": ""})

    assert b"snake-debug-panel" not in body
    assert b"SELECT 1" not in body, "the SQL travelled even without the panel markup"
    assert body == b"<html><body><h1>hi</h1></body></html>"


def test_the_panel_still_reaches_an_html_response_outside_production() -> None:
    """The floor under the test above: out of production the panel is delivered as always.

    Without this pair, dropping the panel unconditionally would satisfy the security test and break
    the feature, and the suite would applaud.
    """
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugWSGI(
        _html_app(driver),
        channels=frozenset({SnakeDebugChannel.SSR}),
        production=False,
    )

    _, body = _run(mw, {"PATH_INFO": "/x", "QUERY_STRING": ""})

    assert b"snake-debug-panel" in body
