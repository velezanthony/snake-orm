"""WHERE the `otel` channel is called from: the same inch of all THREE adapters, and not `Delivery`.

`plan_delivery` is a pure function and `Delivery` is `(headers, envelope)` — two things that modify
the RESPONSE. A network send is neither, and widening that pair to hold an I/O side effect would
dissolve the reason `deliver.py` exists. So the export is a shared function called right after
`report.with_request(...)`, exactly the way `index_advice` is already shared.

In Django it goes OUTSIDE the streaming `if`: a `StreamingHttpResponse` has no body to inject a
panel into, but it produced queries all the same and its report is worth just as much.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable, Iterator, Sequence
from typing import Any

import pytest

from snakeorm.contrib.asgi import Message, SnakeDebugASGI
from snakeorm.contrib.django import SnakeDebugMiddleware
from snakeorm.contrib.wsgi import SnakeDebugWSGI
from snakeorm.debug import CaptureDriver, SnakeDebugChannel
from snakeorm.debug.otel import OtelExporter, set_exporter

_CHANNELS = frozenset({SnakeDebugChannel.OTEL})


class _Inner:
    """Fake driver: it answers one row and records nothing."""

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: no engine behind it, so it yields what `fetch_all` returns."""
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


class _Recorder:
    """A transport that keeps the bodies instead of posting them."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def __call__(self, endpoint: str, body: bytes) -> None:
        self.sent.append(body)


@pytest.fixture
def collected() -> Iterator[list[bytes]]:
    """Install a recording exporter as the process one, and take it out again afterwards."""
    transport = _Recorder()
    exporter = OtelExporter(
        endpoint="http://collector/v1/traces",
        service_name="test",
        transport=transport,
    )
    set_exporter(exporter)
    try:
        yield transport.sent
    finally:
        exporter.flush(timeout=5.0)
        set_exporter(None)
        exporter.shutdown()


def _flush() -> None:
    """Wait for the background worker: the send is deliberately not on the request's thread."""
    from snakeorm.debug.otel import current_exporter

    assert current_exporter().flush(timeout=5.0)


def _spans(bodies: list[bytes]) -> list[dict[str, object]]:
    """The spans of the single exported payload."""
    payload = json.loads(bodies[0])
    return list(payload["resourceSpans"][0]["scopeSpans"][0]["spans"])


def _attributes(span: dict[str, object]) -> dict[str, object]:
    """The span's attributes flattened into a dict, whatever their value tag."""
    entries = span["attributes"]
    assert isinstance(entries, list)
    return {entry["key"]: next(iter(entry["value"].values())) for entry in entries}


# --- WSGI (Flask) --------------------------------------------------------------------------------


def _wsgi_app(
    driver: CaptureDriver,
) -> Callable[[dict[str, str], Callable[..., object]], Iterable[bytes]]:
    """Fake WSGI app: one query and a JSON body."""

    def app(
        environ: dict[str, str], start_response: Callable[..., object]
    ) -> Iterable[bytes]:
        driver.fetch_all("SELECT 1", ())
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b'{"id":7}']

    return app


def test_the_wsgi_adapter_exports_the_report(collected: list[bytes]) -> None:
    """A Flask/WSGI request with the channel on reaches the exporter, request and all."""
    driver = CaptureDriver(_Inner(), system="sqlite")
    middleware = SnakeDebugWSGI(_wsgi_app(driver), channels=_CHANNELS)
    list(middleware({"PATH_INFO": "/orders", "REQUEST_METHOD": "GET"}, lambda *_: None))
    _flush()

    root = _spans(collected)[0]
    assert root["name"] == "GET /orders"
    assert _attributes(root)["url.path"] == "/orders"


def test_the_wsgi_adapter_stays_quiet_without_the_channel(
    collected: list[bytes],
) -> None:
    """With `otel` off nothing is exported: the channel is the switch, as it is for every other."""
    driver = CaptureDriver(_Inner(), system="sqlite")
    middleware = SnakeDebugWSGI(
        _wsgi_app(driver), channels=frozenset({SnakeDebugChannel.TIMING})
    )
    list(middleware({"PATH_INFO": "/orders", "REQUEST_METHOD": "GET"}, lambda *_: None))
    _flush()

    assert collected == []


# --- ASGI (FastAPI) ------------------------------------------------------------------------------


def _asgi_app(driver: CaptureDriver) -> Callable[[Any, Any, Any], Awaitable[None]]:
    """Fake ASGI app: one query and a JSON body."""

    async def app(scope: Any, receive: Any, send: Any) -> None:
        driver.fetch_all("SELECT 1", ())
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"id":7}'})

    return app


def test_the_asgi_adapter_exports_the_report(collected: list[bytes]) -> None:
    """The asynchronous adapter exports the same shape: one seam, two colours."""
    driver = CaptureDriver(_Inner(), system="sqlite")
    middleware = SnakeDebugASGI(_asgi_app(driver), channels=_CHANNELS)
    scope = {"type": "http", "path": "/orders", "method": "GET", "headers": []}

    async def run() -> None:
        await middleware(scope, _receive, _send)

    asyncio.run(run())
    _flush()

    assert _spans(collected)[0]["name"] == "GET /orders"


async def _receive() -> Message:
    """An ASGI `receive` with nothing to give: the fake app never reads a body."""
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(message: Message) -> None:
    """An ASGI `send` that drops the response: this test looks at the spans, not the body."""


# --- Django ---------------------------------------------------------------------------------------


class _FakeRequest:
    """Minimal request double: the middleware reads path, method and headers."""

    def __init__(self, path: str = "/orders") -> None:
        self.path = path
        self.method = "GET"
        self.META: dict[str, str] = {"QUERY_STRING": ""}


class _FakeResponse:
    """Minimal HttpResponse double: content and headers through `[]`/`get`."""

    def __init__(self, content: bytes = b'{"id":7}') -> None:
        self.content = content
        self.status_code = 200
        self._headers = {"Content-Type": "application/json"}

    def get(self, name: str, default: str = "") -> str:
        return self._headers.get(name, default)

    def __setitem__(self, name: str, value: str) -> None:
        self._headers[name] = value


class _StreamingResponse:
    """A `StreamingHttpResponse` double: `streaming` is true and touching `.content` raises."""

    streaming = True
    status_code = 200

    def __init__(self) -> None:
        self._headers: dict[str, str] = {}

    @property
    def content(self) -> bytes:
        raise AttributeError("a streaming response has no content")

    def get(self, name: str, default: str = "") -> str:
        return self._headers.get(name, default)

    def __setitem__(self, name: str, value: str) -> None:
        self._headers[name] = value


def test_the_django_adapter_exports_the_report(
    collected: list[bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Django request with the channel on exports its report."""
    monkeypatch.setenv("SNAKE_ORM_DEBUG", "otel")
    driver = CaptureDriver(_Inner(), system="sqlite")

    def view(request: object) -> _FakeResponse:
        driver.fetch_all("SELECT 1", ())
        return _FakeResponse()

    SnakeDebugMiddleware(view)(_FakeRequest())
    _flush()

    assert _spans(collected)[0]["name"] == "GET /orders"


def test_a_streaming_response_still_exports(
    collected: list[bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The BODY is skipped for a streaming response; the REPORT is not.

    The export sits outside the streaming `if` on purpose. A `StreamingHttpResponse` has nowhere to
    put a panel, but it ran the same queries — and dropping its trace would hide exactly the
    endpoints that stream because they are big.
    """
    monkeypatch.setenv("SNAKE_ORM_DEBUG", "otel")
    driver = CaptureDriver(_Inner(), system="sqlite")

    def view(request: object) -> _StreamingResponse:
        driver.fetch_all("SELECT 1", ())
        return _StreamingResponse()

    SnakeDebugMiddleware(view)(_FakeRequest("/export.csv"))
    _flush()

    assert _spans(collected)[0]["name"] == "GET /export.csv"


def test_the_exported_children_carry_the_engine(collected: list[bytes]) -> None:
    """The engine declared on the capture driver arrives on the child span as `db.system.name`."""
    driver = CaptureDriver(_Inner(), system="sqlite")
    middleware = SnakeDebugWSGI(_wsgi_app(driver), channels=_CHANNELS)
    list(middleware({"PATH_INFO": "/orders", "REQUEST_METHOD": "GET"}, lambda *_: None))
    _flush()

    _root, child = _spans(collected)
    assert _attributes(child)["db.system.name"] == "sqlite"
