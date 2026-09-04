"""The same trap, over the REAL Django, whose notion of "outside" is the one that reads backwards.

In Django the OUTERMOST middleware is the FIRST entry of `MIDDLEWARE`, so the rule flips against the
other two: where Flask and FastAPI want ours declared FIRST (later assignments/calls wrap it), Django
wants it declared SECOND, under the OpenTelemetry one. Getting that backwards costs nothing visible —
the traces arrive, detached — which is why it is checked here rather than remembered.

Django is configured in this module and only in this module: it declares `DEBUG=True`, which is what
`SnakeDebugMiddleware` already assumes when Django is absent, so the rest of the suite sees no
change.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence

import pytest

from snakeorm.debug import CaptureDriver
from snakeorm.debug.otel import OtelExporter, set_exporter

django = pytest.importorskip("django")
trace = pytest.importorskip("opentelemetry.trace")
sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")

from django.conf import settings  # noqa: E402
from django.http import HttpRequest, HttpResponse  # noqa: E402
from django.urls import path  # noqa: E402

_TRACER = sdk_trace.TracerProvider().get_tracer("test-application")
_OPENED: list[object] = []

_SNAKE = "snakeorm.contrib.django.SnakeDebugMiddleware"
_SPAN = "test.contrib.test_otel_middleware_order_django.SpanMiddleware"


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


_DRIVER = CaptureDriver(_Inner(), system="sqlite")


class SpanMiddleware:
    """Stands in for an OpenTelemetry agent: it opens a real server span around the view."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Wrap the rest of the chain in a span and remember it, so a test can name the parent."""
        with _TRACER.start_as_current_span("GET /orders") as span:
            _OPENED.append(span)
            return self._get_response(request)


def orders(request: HttpRequest) -> HttpResponse:
    """A view that runs one query, which is all the report needs."""
    _DRIVER.fetch_all("SELECT 1", ())
    return HttpResponse("ok")


urlpatterns = [path("orders", orders)]
"""This module is its own `ROOT_URLCONF`: one file, no fixtures pointing at another."""


@pytest.fixture(autouse=True, scope="module")
def _django_settings() -> Iterator[None]:
    """Configure Django once for this module, with this file as its URLconf."""
    if not settings.configured:
        settings.configure(
            DEBUG=True,
            SECRET_KEY="test",
            ALLOWED_HOSTS=["*"],
            ROOT_URLCONF=__name__,
            DATABASES={},
            MIDDLEWARE=[],
            USE_TZ=True,
        )
        django.setup()
    yield


class _Recorder:
    """A transport that keeps the bodies instead of posting them."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def __call__(self, endpoint: str, body: bytes) -> None:
        self.sent.append(body)


@pytest.fixture
def collected(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[bytes]]:
    """A recording exporter as the process one, and `otel` as the only channel Django reads."""
    monkeypatch.setenv("SNAKE_ORM_DEBUG", "otel")
    _OPENED.clear()
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


def _root(bodies: list[bytes]) -> dict[str, object]:
    """The root span of the single exported payload."""
    from snakeorm.debug.otel import current_exporter

    assert current_exporter().flush(timeout=5.0)
    span = json.loads(bodies[0])["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert isinstance(span, dict)
    return span


def _get(middleware: list[str]) -> None:
    """Run `GET /orders` through Django with that middleware stack."""
    from django.test import Client, override_settings

    with override_settings(MIDDLEWARE=middleware):
        Client().get("/orders")


def test_django_with_otel_first_finds_the_parent(collected: list[bytes]) -> None:
    """OTel FIRST in `MIDDLEWARE` (outermost) and ours under it: the app's span is still open."""
    _get([_SPAN, _SNAKE])

    root = _root(collected)
    context = _OPENED[0].get_span_context()  # type: ignore[attr-defined]
    assert root["parentSpanId"] == format(context.span_id, "016x")
    assert root["traceId"] == format(context.trace_id, "032x")
    assert (
        root["kind"] == 1
    )  # INTERNAL: theirs is the server span, ours a section inside it


def test_django_with_snakeorm_first_is_orphaned(collected: list[bytes]) -> None:
    """Ours FIRST: by the time we deliver the report the app's span has closed, and we float.

    Nothing raises and nothing goes red. Loose traces arrive and the suite stays green, which is
    exactly why the order is written down where a user configures it.
    """
    _get([_SNAKE, _SPAN])

    root = _root(collected)
    assert "parentSpanId" not in root
    assert (
        root["kind"] == 2
    )  # SERVER: with nothing above it, ours IS the request's span
