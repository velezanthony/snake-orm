"""The exporter: a BACKGROUND QUEUE from day one, and a failure that says so.

The queue is not an optimisation. Exporting in line adds ~210 ms to a request of 503 queries against
localhost, and on the asynchronous path that blocks the WHOLE event loop, not just the request that
paid for it. So `submit` hands the report to a worker thread and returns; the HTTP POST happens over
there.

A telemetry backend that is down must not take an application down either, so a failed send is
counted and warned about ONCE — never a silent drop, which is the failure this ORM exists not to
commit, and never an exception into the request.
"""

from __future__ import annotations

import warnings

import pytest

from snakeorm.core.exceptions import SnakeWarning
from snakeorm.debug import DebugReport, QueryKind, QueryRecord, SnakeDebugChannel
from snakeorm.debug.otel import (
    DEFAULT_ENDPOINT,
    DEFAULT_SERVICE_NAME,
    OtelExporter,
    current_exporter,
    endpoint_from_env,
    export_report,
    service_name_from_env,
    set_exporter,
)


def _report() -> DebugReport:
    """A one-query report, enough to produce a root and a child."""
    record = QueryRecord(
        n=1,
        sql='SELECT * FROM "orders"',
        params=(),
        duration_ms=1.0,
        rows=1,
        kind=QueryKind.SELECT,
        started_at=1.0,
        system="postgresql",
    )
    return DebugReport((record,))


class _Recorder:
    """A transport that keeps what it was asked to send instead of sending it."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []

    def __call__(self, endpoint: str, body: bytes) -> None:
        self.sent.append((endpoint, body))


class _Broken:
    """A transport that always fails, the way an unreachable collector does."""

    def __call__(self, endpoint: str, body: bytes) -> None:
        raise OSError("connection refused")


def test_a_submitted_report_reaches_the_transport() -> None:
    """The end to end of the exporter: submit a report, the worker posts its payload."""
    transport = _Recorder()
    exporter = OtelExporter(
        endpoint="http://collector/v1/traces",
        service_name="demo",
        transport=transport,
    )
    try:
        exporter.submit(_report())
        assert exporter.flush(timeout=5.0)
    finally:
        exporter.shutdown()

    endpoint, body = transport.sent[0]
    assert endpoint == "http://collector/v1/traces"
    assert b"resourceSpans" in body


def test_submitting_does_not_send_on_the_calling_thread() -> None:
    """`submit` returns before the transport runs: the request never pays for the export.

    The transport blocks until the test releases it, so if `submit` were doing the sending this
    would deadlock instead of returning.
    """
    import threading

    released = threading.Event()
    started = threading.Event()

    def blocking(endpoint: str, body: bytes) -> None:
        started.set()
        released.wait(timeout=5.0)

    exporter = OtelExporter(
        endpoint="http://collector/v1/traces", service_name="demo", transport=blocking
    )
    try:
        exporter.submit(_report())
        assert started.wait(timeout=5.0)
    finally:
        released.set()
        exporter.shutdown()


def test_a_full_queue_drops_instead_of_blocking() -> None:
    """With the queue full the report is DROPPED and counted: telemetry never slows a request down."""
    import threading

    released = threading.Event()

    def blocking(endpoint: str, body: bytes) -> None:
        released.wait(timeout=5.0)

    exporter = OtelExporter(
        endpoint="http://collector/v1/traces",
        service_name="demo",
        transport=blocking,
        queue_size=1,
    )
    try:
        for _ in range(20):
            exporter.submit(_report())
    finally:
        released.set()
        exporter.shutdown()

    assert exporter.dropped > 0


def test_a_failing_transport_never_reaches_the_caller() -> None:
    """A collector that is down raises inside the worker and NOT into the request."""
    exporter = OtelExporter(
        endpoint="http://collector/v1/traces",
        service_name="demo",
        transport=_Broken(),
    )
    try:
        exporter.submit(_report())
        assert exporter.flush(timeout=5.0)
    finally:
        exporter.shutdown()

    assert exporter.failures == 1


def test_the_first_failure_warns_and_the_rest_stay_quiet() -> None:
    """One `SnakeWarning` names the endpoint and the reason; the following ones do not repeat it.

    A drop that says nothing is the silence this project pays for; a drop that says it on every
    request is a log nobody reads. Once, naming the endpoint, is the line.
    """
    exporter = OtelExporter(
        endpoint="http://collector/v1/traces",
        service_name="demo",
        transport=_Broken(),
    )
    with pytest.warns(SnakeWarning, match="http://collector/v1/traces"):
        exporter.send_now(_report(), parent=None)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        exporter.send_now(_report(), parent=None)

    assert exporter.failures == 2


def test_the_endpoint_comes_from_the_standard_variables() -> None:
    """`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` wins; the generic one gets `/v1/traces` appended."""
    assert (
        endpoint_from_env({"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://jaeger/tr"})
        == "http://jaeger/tr"
    )
    assert (
        endpoint_from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://jaeger:4318"})
        == "http://jaeger:4318/v1/traces"
    )


def test_a_trailing_slash_does_not_double_up() -> None:
    """`http://jaeger:4318/` gives one slash, not two: the collector 404s on a doubled path."""
    assert (
        endpoint_from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://jaeger:4318/"})
        == "http://jaeger:4318/v1/traces"
    )


def test_without_variables_it_falls_back_to_the_local_collector() -> None:
    """No configuration means the local OTLP/HTTP port, which is what `docker compose` publishes."""
    assert endpoint_from_env({}) == DEFAULT_ENDPOINT
    assert service_name_from_env({}) == DEFAULT_SERVICE_NAME


def test_the_service_name_comes_from_the_standard_variable() -> None:
    """`OTEL_SERVICE_NAME` is the name every other exporter reads: no vocabulary of our own."""
    assert service_name_from_env({"OTEL_SERVICE_NAME": "flask-demo"}) == "flask-demo"


def test_export_report_does_nothing_without_the_channel() -> None:
    """With `otel` off, exporting is one frozenset membership test and no exporter is ever built."""
    transport = _Recorder()
    exporter = OtelExporter(
        endpoint="http://collector/v1/traces",
        service_name="demo",
        transport=transport,
    )
    set_exporter(exporter)
    try:
        export_report(_report(), frozenset({SnakeDebugChannel.TIMING}))
        assert exporter.flush(timeout=5.0)
    finally:
        set_exporter(None)
        exporter.shutdown()

    assert transport.sent == []


def test_export_report_queues_when_the_channel_is_on() -> None:
    """With `otel` on, the report reaches the process exporter and gets sent."""
    transport = _Recorder()
    exporter = OtelExporter(
        endpoint="http://collector/v1/traces",
        service_name="demo",
        transport=transport,
    )
    set_exporter(exporter)
    try:
        export_report(_report(), frozenset({SnakeDebugChannel.OTEL}))
        assert current_exporter().flush(timeout=5.0)
    finally:
        set_exporter(None)
        exporter.shutdown()

    assert len(transport.sent) == 1


def test_the_process_exporter_is_built_once_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`current_exporter()` reads the standard variables once and hands the SAME instance back.

    One background thread for the process, not one per request: that is what makes the queue a queue.
    """
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "flask-demo")
    set_exporter(None)
    try:
        exporter = current_exporter()

        assert exporter is current_exporter()
        assert exporter.endpoint == "http://jaeger:4318/v1/traces"
        assert exporter.service_name == "flask-demo"
    finally:
        set_exporter(None)
