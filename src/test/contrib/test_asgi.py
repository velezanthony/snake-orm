"""The ASGI adapter (FastAPI/Starlette), tested over PURE ASGI —without installing FastAPI—.

An ASGI middleware is just `async def __call__(scope, receive, send)`, so it is exercised with a fake
app and a `send` that collects the messages. That is the advantage of the adapter depending on the
ASGI SPEC and not on a framework's class: it is tested without dragging in the dependency.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator, Sequence
from typing import Any

from snakeorm.contrib.asgi import SnakeDebugASGI
from snakeorm.debug import CaptureDriver, SnakeDebugChannel, SnakeDebugConfig

ASGIApp = Callable[[Any, Any, Any], Awaitable[None]]


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


def _json_app(driver: CaptureDriver, body: bytes = b'{"id":7}') -> ASGIApp:
    """Fake ASGI app: it runs a query and returns a JSON."""

    async def app(scope: Any, receive: Any, send: Any) -> None:
        driver.fetch_all("SELECT 1", ())
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return app


def _run(middleware: SnakeDebugASGI, scope: dict[str, Any]) -> list[dict[str, Any]]:
    """Runs the middleware with a scope and returns the ASGI messages emitted."""
    sent: list[dict[str, Any]] = []

    async def send(message: Any) -> None:
        sent.append(message)

    async def receive() -> Any:
        return {"type": "http.request"}

    asyncio.run(middleware(scope, receive, send))
    return sent


def _scope(path: str = "/users/7", query: bytes = b"") -> dict[str, Any]:
    return {"type": "http", "path": path, "query_string": query, "headers": []}


def test_envelope_injected_when_channel_on() -> None:
    """With the `envelope` channel, the JSON gains a `snakeorm` block on EVERY response (no trigger)."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugASGI(
        _json_app(driver),
        channels=frozenset({SnakeDebugChannel.ENVELOPE}),
        production=False,
    )
    sent = _run(mw, _scope())  # no ?_debug=1: the channel is the switch
    body = next(m["body"] for m in sent if m["type"] == "http.response.body")
    data = json.loads(body)
    assert data["id"] == 7
    assert data["snakeorm"]["count"] == 1


def test_no_envelope_when_channel_off() -> None:
    """Without the `envelope` channel, the JSON comes back untouched (the normal response is not dirtied)."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugASGI(
        _json_app(driver),
        channels=frozenset({SnakeDebugChannel.TIMING}),
        production=False,
    )
    sent = _run(mw, _scope())
    body = next(m["body"] for m in sent if m["type"] == "http.response.body")
    assert json.loads(body) == {"id": 7}


def test_envelope_wraps_a_top_level_array() -> None:
    """An endpoint returning a top-level ARRAY gains debug too: it gets wrapped in `{data, snakeorm}`."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugASGI(
        _json_app(driver, body=b"[1,2,3]"),
        channels=frozenset({SnakeDebugChannel.ENVELOPE}),
        production=False,
    )
    sent = _run(mw, _scope())
    body = next(m["body"] for m in sent if m["type"] == "http.response.body")
    data = json.loads(body)
    assert data["data"] == [1, 2, 3]
    assert data["snakeorm"]["count"] == 1


def test_timing_header_added() -> None:
    """The `timing` channel adds the Server-Timing header to the response."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugASGI(
        _json_app(driver),
        channels=frozenset({SnakeDebugChannel.TIMING}),
        production=False,
    )
    sent = _run(mw, _scope())
    start = next(m for m in sent if m["type"] == "http.response.start")
    names = {key.lower() for key, _ in start["headers"]}
    assert b"server-timing" in names


def test_production_strips_envelope() -> None:
    """In production, the `envelope` channel drops even if asked for: it does not leak SQL."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugASGI(
        _json_app(driver),
        channels=frozenset({SnakeDebugChannel.ENVELOPE}),
        production=True,
    )
    sent = _run(mw, _scope())
    body = next(m["body"] for m in sent if m["type"] == "http.response.body")
    assert "snakeorm" not in json.loads(body)


def test_sidecar_serves_the_panel_page() -> None:
    """With `sidecar`, the response carries a token and `/__snake__/{token}` serves the HTML panel."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugASGI(
        _json_app(driver),
        channels=frozenset({SnakeDebugChannel.SIDECAR}),
        production=False,
    )
    sent = _run(mw, _scope())
    start = next(m for m in sent if m["type"] == "http.response.start")
    token = next(
        value.decode()
        for key, value in start["headers"]
        if key.lower() == b"x-debug-token"
    )
    page = _run(mw, _scope(path=f"/__snake__/{token}"))
    body = next(m["body"] for m in page if m["type"] == "http.response.body")
    assert b"snake-debug-panel" in body


def _html_app(driver: CaptureDriver) -> ASGIApp:
    """Fake ASGI app: it runs a query and returns an HTML page."""

    async def app(scope: Any, receive: Any, send: Any) -> None:
        driver.fetch_all("SELECT 1", ())
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/html; charset=utf-8")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"<html><body><h1>hi</h1></body></html>",
            }
        )

    return app


def _body_of(sent: list[dict[str, Any]]) -> bytes:
    """The body of the emitted ASGI messages."""
    return next(m["body"] for m in sent if m["type"] == "http.response.body")


def test_ssr_panel_carries_the_configured_csp_nonce() -> None:
    """The `csp_nonce` of `SnakeDebugConfig` reaches the panel delivered by the middleware.

    Without it, an app with a strict CSP gets the panel blocked by the browser and no error
    anywhere: the config was declared and the adapter dropped it on the floor.
    """
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugASGI(
        _html_app(driver),
        channels=frozenset({SnakeDebugChannel.SSR}),
        config=SnakeDebugConfig(csp_nonce="r4nd0m"),
        production=False,
    )
    assert b'<script type="module" nonce="r4nd0m">' in _body_of(_run(mw, _scope()))


def test_ssr_panel_without_a_nonce_is_unchanged() -> None:
    """With no nonce configured, the delivered HTML carries no nonce at all (output unchanged)."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugASGI(
        _html_app(driver),
        channels=frozenset({SnakeDebugChannel.SSR}),
        config=SnakeDebugConfig(),
        production=False,
    )
    body = _body_of(_run(mw, _scope()))
    assert b"snake-debug-panel" in body
    assert b"nonce" not in body


def test_the_report_names_the_request_it_came_from() -> None:
    """The ASGI adapter fills the identity out of the scope: method, path and the response status."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugASGI(
        _json_app(driver),
        channels=frozenset({SnakeDebugChannel.ENVELOPE}),
        production=False,
    )

    scope = _scope(path="/api/posts")
    scope["method"] = "DELETE"
    sent = _run(mw, scope)

    body = next(m["body"] for m in sent if m["type"] == "http.response.body")
    request = json.loads(body)["snakeorm"]["request"]
    assert request["method"] == "DELETE"
    assert request["path"] == "/api/posts"
    assert request["status"] == 200
    assert request["at"]
