"""Reading the ACTIVE trace context, which is the only thing `opentelemetry-api` is here for.

Everything else in this channel is stdlib. The API buys one irreplaceable thing: whether the
application already has a span open, and which one, so our spans hang off it instead of floating.
It degrades in three ways and all three are tested, because two of them are the NORMAL state of an
application that has not adopted OpenTelemetry — and neither may raise.
"""

from __future__ import annotations

import sys

import pytest

from snakeorm.debug.otel import TraceContext, active_context


def test_no_active_span_gives_no_context() -> None:
    """Outside any span the context is `None`: our root becomes the request's server span."""
    assert active_context() is None


def test_a_missing_library_gives_no_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """With `opentelemetry` not installed, the `ImportError` is caught and the channel keeps working.

    The API is an OPTIONAL extra. An application that never installed it still gets its traces —
    loose roots instead of children, which is the honest degradation.
    """
    monkeypatch.setitem(sys.modules, "opentelemetry", None)

    assert active_context() is None


def test_an_active_span_is_read_as_hex_ids() -> None:
    """Inside a real span, its trace and span ids come back in the hex form OTLP/JSON wants.

    32 hex characters for the trace and 16 for the span: that is `traceId` and `parentSpanId` in the
    payload, and it is what makes Jaeger draw one tree instead of two.
    """
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")

    tracer = sdk_trace.TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("server") as span:
        context = active_context()
        expected = span.get_span_context()

    assert context == TraceContext(
        trace_id=format(expected.trace_id, "032x"),
        span_id=format(expected.span_id, "016x"),
    )


def test_a_failing_provider_is_swallowed_rather_than_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any failure reading the context degrades to `None`: telemetry never takes a request down."""
    trace = pytest.importorskip("opentelemetry.trace")

    def exploding() -> object:
        raise RuntimeError("the provider is in a bad way")

    monkeypatch.setattr(trace, "get_current_span", exploding)

    assert active_context() is None
