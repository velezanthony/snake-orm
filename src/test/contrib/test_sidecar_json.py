"""`/__snake__/{token}` answers TWO readers, and the token decides nothing about which.

The sidecar was written for a person opening a URL, so it only ever rendered the panel PAGE. The
history tab is the other reader: it holds a `X-Debug-Token` off a response whose body it cannot see
(an HTML fragment carries its report in the headers) and it needs the report itself, not a document
that embeds a copy of the whole panel inside the panel.

So the same URL negotiates: `Accept: application/json` gets `DebugReport.to_dict()` — the very
dictionary the `envelope` channel already hangs off JSON responses, so both paths of the history
read ONE shape. Everything else keeps getting the page, byte for byte as before.

The 404 does NOT negotiate, on purpose: there is one sentence for an evicted report and two
serialisations of it would be two sentences to keep in step. A client that asked for JSON and got
`404` has its answer before it parses anything.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable, Iterator, MutableMapping, Sequence
from typing import Any

import pytest

from snakeorm.contrib.asgi import SnakeDebugASGI
from snakeorm.contrib.deliver import SIDECAR_UNKNOWN_TOKEN_BODY, serve_sidecar
from snakeorm.contrib.wsgi import SnakeDebugWSGI
from snakeorm.debug import CaptureDriver, SnakeDebugChannel
from snakeorm.debug.record import QueryKind, QueryOrigin, QueryRecord
from snakeorm.debug.report import DebugReport

_JSON = "application/json"
_CHANNELS = frozenset({SnakeDebugChannel.SIDECAR})


def _report() -> DebugReport:
    """A one-query report, enough for the dictionary to carry a query and a count."""
    record = QueryRecord(
        n=1,
        sql="SELECT 1",
        params=(),
        duration_ms=2.5,
        rows=1,
        kind=QueryKind.SELECT,
        origin=QueryOrigin(file="/app/views.py", line=10, function="index"),
    )
    return DebugReport.from_records([record], wall_ms=9.0)


def test_the_sidecar_still_serves_the_page_to_a_browser() -> None:
    """With no `Accept` asking for JSON, the sidecar answers the panel page as it always did."""
    page = serve_sidecar(_report())

    assert page.status == 200
    assert page.content_type == "text/html; charset=utf-8"
    assert b"snake-debug-panel" in page.body


def test_the_sidecar_serves_the_report_as_json_when_asked() -> None:
    """`Accept: application/json` gets the report itself, not a document that contains the panel."""
    page = serve_sidecar(_report(), accept="application/json")

    assert page.status == 200
    assert page.content_type == "application/json; charset=utf-8"
    assert b"snake-debug-panel" not in page.body


def test_the_json_the_sidecar_serves_is_the_envelope_dictionary() -> None:
    """The JSON body IS `DebugReport.to_dict()`: the history reads ONE shape from both channels.

    The envelope hangs that same dictionary off a JSON response. If the sidecar invented a second
    shape, the tab would need two readers for one report and they would drift.
    """
    report = _report()
    page = serve_sidecar(report, accept="application/json")

    assert json.loads(page.body) == json.loads(json.dumps(report.to_dict()))


def test_an_evicted_report_answers_the_same_sentence_to_both_readers() -> None:
    """A gone token answers 404 with the one shared body, whatever the reader asked for.

    Negotiating the 404 too would mean two wordings of one fact, which is the drift
    `SIDECAR_UNKNOWN_TOKEN_BODY` exists to stop.
    """
    for accept in ("", "application/json", "text/html"):
        page = serve_sidecar(None, accept=accept)

        assert page.status == 404, accept
        assert page.body == SIDECAR_UNKNOWN_TOKEN_BODY, accept


class _Inner:
    """Driver double: it answers one row without an engine behind it."""

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
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


def _wsgi_json() -> bytes:
    """The body the WSGI adapter serves for a live token asked for as JSON."""
    driver = CaptureDriver(_Inner())

    def app(
        environ: dict[str, str], start_response: Callable[..., object]
    ) -> Iterable[bytes]:
        driver.fetch_all("SELECT 1", ())
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [b"<html><body>hi</body></html>"]

    middleware = SnakeDebugWSGI(app, channels=_CHANNELS, production=False)
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> object:
        captured["status"] = status
        captured["headers"] = headers
        return None

    b"".join(middleware({"PATH_INFO": "/x", "QUERY_STRING": ""}, start_response))
    token = next(
        value for key, value in captured["headers"] if key.lower() == "x-debug-token"
    )
    return b"".join(
        middleware(
            {"PATH_INFO": f"/__snake__/{token}", "HTTP_ACCEPT": _JSON}, start_response
        )
    )


def _asgi_json() -> bytes:
    """The body the ASGI adapter serves for a live token asked for as JSON."""
    driver = CaptureDriver(_Inner())

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
            {"type": "http.response.body", "body": b"<html><body>hi</body></html>"}
        )

    middleware = SnakeDebugASGI(app, channels=_CHANNELS, production=False)

    async def run(scope: dict[str, Any]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []

        async def send(message: MutableMapping[str, Any]) -> None:
            messages.append(dict(message))

        async def receive() -> MutableMapping[str, Any]:
            return {"type": "http.request", "body": b""}

        await middleware(scope, receive, send)
        return messages

    first = asyncio.run(run({"type": "http", "path": "/x", "method": "GET"}))
    start = next(item for item in first if item["type"] == "http.response.start")
    token = next(
        value.decode()
        for key, value in start["headers"]
        if key.lower() == b"x-debug-token"
    )
    second = asyncio.run(
        run(
            {
                "type": "http",
                "path": f"/__snake__/{token}",
                "method": "GET",
                "headers": [(b"accept", _JSON.encode())],
            }
        )
    )
    return b"".join(
        bytes(item.get("body", b""))
        for item in second
        if item["type"] == "http.response.body"
    )


@pytest.mark.parametrize("body_of", [_wsgi_json, _asgi_json], ids=["wsgi", "asgi"])
def test_the_adapters_pass_the_accept_header_through(
    body_of: Callable[[], bytes],
) -> None:
    """WSGI and ASGI read `Accept` off their own request shape and serve the report as JSON.

    The negotiation is decided once in `serve_sidecar`; what each adapter still owns is finding the
    header in its own protocol — `HTTP_ACCEPT` in a WSGI environ, a bytes pair in an ASGI scope. A
    middleware that never looked would silently keep serving the page, and the tab would try to
    parse a document.
    """
    payload = json.loads(body_of())

    assert payload["count"] == 1
    assert payload["queries"][0]["sql"] == "SELECT 1"
