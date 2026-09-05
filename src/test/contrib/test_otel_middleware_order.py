"""THE TRAP: whichever middleware is on the OUTSIDE decides whether our spans have a parent.

```
OTel OUTSIDE / SnakeORM INSIDE  ->  parent found
SnakeORM OUTSIDE / OTel INSIDE  ->  ORPHAN
```

If our middleware is the outer one, the application's server span has ALREADY CLOSED by the time we
deliver the report, so `trace.get_current_span()` gives nothing and the spans come out as loose
roots. Nothing fails: the traces are simply detached, and a suite that only checks "a trace arrived"
stays green through it.

This was measured with equivalent wrappers, never over the real frameworks — which is exactly where
it matters, because each of the three spells "outside" differently:

| framework | the outermost one is |
|-----------|----------------------|
| Django    | the FIRST entry of `MIDDLEWARE` |
| Flask     | the LAST `app.wsgi_app = ...` assignment |
| FastAPI   | the LAST `app.add_middleware(...)` call |

So this file runs the real Django, the real Flask and the real FastAPI, in both orders each.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterator, Sequence

import pytest

from snakeorm.contrib.asgi import SnakeDebugASGI
from snakeorm.contrib.wsgi import SnakeDebugWSGI
from snakeorm.debug import CaptureDriver, SnakeDebugChannel
from snakeorm.debug.otel import OtelExporter, set_exporter

trace = pytest.importorskip("opentelemetry.trace")
sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")

_CHANNELS = frozenset({SnakeDebugChannel.OTEL})
_TRACER = sdk_trace.TracerProvider().get_tracer("test-application")


class _Inner:
    """Fake driver: one row, no engine behind it."""

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: no engine to stream from, so it yields what `fetch_all` returns."""
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
    """Wait for the background worker before reading what it sent."""
    from snakeorm.debug.otel import current_exporter

    assert current_exporter().flush(timeout=5.0)


def _root(bodies: list[bytes]) -> dict[str, object]:
    """The root span of the single exported payload (ours is always emitted first)."""
    payload = json.loads(bodies[0])
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert isinstance(span, dict)
    return span


def _assert_adopted(bodies: list[bytes], parent: object) -> None:
    """Our root hangs off the application's span: same trace, and the app's span as parent."""
    _flush()
    root = _root(bodies)
    context = parent.get_span_context()  # type: ignore[attr-defined]

    assert root["parentSpanId"] == format(context.span_id, "016x")
    assert root["traceId"] == format(context.trace_id, "032x")
    assert root["kind"] == 1  # INTERNAL: the application's is the server span, not ours


def _assert_orphaned(bodies: list[bytes]) -> None:
    """Our root floats: no parent and a trace of its own. Nothing failed — that is the danger."""
    _flush()
    root = _root(bodies)

    assert "parentSpanId" not in root
    assert (
        root["kind"] == 2
    )  # SERVER: with nothing above it, ours IS the request's span


# --- Flask, over the REAL framework ---------------------------------------------------------------


def _flask_pieces() -> tuple[object, CaptureDriver, list[object]]:
    """A real Flask app with one view that runs a query, plus the span the wrapper opened."""
    flask = pytest.importorskip("flask")
    driver = CaptureDriver(_Inner(), system="sqlite")
    opened: list[object] = []

    app = flask.Flask(__name__)

    @app.get("/orders")
    def orders() -> str:
        driver.fetch_all("SELECT 1", ())
        return "ok"

    return app, driver, opened


def _wsgi_span(inner: object, opened: list[object]) -> Callable[..., object]:
    """A WSGI wrapper that opens a real span around the application, the way an agent would."""

    def middleware(environ: dict[str, str], start_response: object) -> object:
        with _TRACER.start_as_current_span("GET /orders") as span:
            opened.append(span)
            return inner(environ, start_response)  # type: ignore[operator]

    return middleware


def test_flask_with_otel_outside_finds_the_parent(collected: list[bytes]) -> None:
    """Flask: assigning `wsgi_app` LAST puts OTel outside, and our spans hang off the app's."""
    app, _driver, opened = _flask_pieces()
    app.wsgi_app = SnakeDebugWSGI(app.wsgi_app, channels=_CHANNELS)  # type: ignore[attr-defined]
    app.wsgi_app = _wsgi_span(app.wsgi_app, opened)  # type: ignore[attr-defined]
    app.test_client().get("/orders")  # type: ignore[attr-defined]

    _assert_adopted(collected, opened[0])


def test_flask_with_snakeorm_outside_is_orphaned(collected: list[bytes]) -> None:
    """Flask, the orders swapped: our middleware runs last, the app's span is already closed."""
    app, _driver, opened = _flask_pieces()
    app.wsgi_app = _wsgi_span(app.wsgi_app, opened)  # type: ignore[attr-defined]
    app.wsgi_app = SnakeDebugWSGI(app.wsgi_app, channels=_CHANNELS)  # type: ignore[attr-defined]
    app.test_client().get("/orders")  # type: ignore[attr-defined]

    _assert_orphaned(collected)


# --- FastAPI, over the REAL framework -------------------------------------------------------------


class _AsgiSpan:
    """An ASGI wrapper that opens a real span around the application, the way an agent would."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self._app = app

    async def __call__(self, scope: object, receive: object, send: object) -> None:
        with _TRACER.start_as_current_span("GET /orders") as span:
            _OPENED.append(span)
            await self._app(scope, receive, send)


_OPENED: list[object] = []


def _fastapi_app() -> object:
    """A real FastAPI app with one endpoint that runs a query."""
    fastapi = pytest.importorskip("fastapi")
    driver = CaptureDriver(_Inner(), system="sqlite")
    app = fastapi.FastAPI()

    @app.get("/orders")
    async def orders() -> dict[str, int]:
        driver.fetch_all("SELECT 1", ())
        return {"id": 7}

    return app


def test_fastapi_with_otel_outside_finds_the_parent(collected: list[bytes]) -> None:
    """FastAPI: `add_middleware` builds INWARDS, so the LAST one added is the outer one."""
    testclient = pytest.importorskip("starlette.testclient")
    _OPENED.clear()
    app = _fastapi_app()
    app.add_middleware(SnakeDebugASGI, channels=_CHANNELS)  # type: ignore[attr-defined]
    app.add_middleware(_AsgiSpan)  # type: ignore[attr-defined]
    testclient.TestClient(app).get("/orders")

    _assert_adopted(collected, _OPENED[0])


def test_fastapi_with_snakeorm_outside_is_orphaned(collected: list[bytes]) -> None:
    """FastAPI, the orders swapped: adding ours last puts it outside, and the parent is gone."""
    testclient = pytest.importorskip("starlette.testclient")
    _OPENED.clear()
    app = _fastapi_app()
    app.add_middleware(_AsgiSpan)  # type: ignore[attr-defined]
    app.add_middleware(SnakeDebugASGI, channels=_CHANNELS)  # type: ignore[attr-defined]
    testclient.TestClient(app).get("/orders")

    _assert_orphaned(collected)
