"""Sending the spans: OTLP over HTTP, from a BACKGROUND QUEUE, with `urllib` and nothing else.

The queue is not an optimisation and it is not deferred to a later version. Measured against
localhost, exporting in line adds ~210 ms to a request of 503 queries; on the asynchronous path that
does not slow one request down, it blocks the WHOLE event loop. So `submit` reads the active trace
context —which has to happen on the calling thread, because that is where the context lives— hands
the report to a worker and returns.

Two failure modes, and both are declared rather than swallowed. A full queue DROPS (telemetry must
never make an application wait) and counts the drop. A transport that fails counts the failure and
warns ONCE, naming the endpoint: a silence would be the exact fault this ORM exists not to commit,
and a warning per request would be a log nobody reads.
"""

from __future__ import annotations

import atexit
import os
import queue
import threading
import warnings
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from snakeorm.core.exceptions import SnakeWarning
from snakeorm.debug.otel.context import TraceContext, active_context
from snakeorm.debug.otel.payload import encode_payload, otlp_payload
from snakeorm.debug.otel.spans import spans_from_report

if TYPE_CHECKING:
    from snakeorm.debug.report import DebugReport

Transport = Callable[[str, bytes], None]
"""How the body actually leaves: `(endpoint, body) -> None`. Injected, so it is testable offline."""

DEFAULT_ENDPOINT = "http://localhost:4318/v1/traces"
"""The local OTLP/HTTP port, which is the one `docker compose --profile tracing` publishes."""

DEFAULT_SERVICE_NAME = "snakeorm"
"""What Jaeger's Service dropdown says when the application did not name itself."""

TRACES_ENDPOINT_ENV_KEY = "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
ENDPOINT_ENV_KEY = "OTEL_EXPORTER_OTLP_ENDPOINT"
SERVICE_NAME_ENV_KEY = "OTEL_SERVICE_NAME"
# The STANDARD variable names, not ours. Anyone who has configured any other exporter has already
# set them, and a private spelling would be one more thing to discover.

_TRACES_PATH = "/v1/traces"
_HTTP_TIMEOUT_SECONDS = 5.0
_DEFAULT_QUEUE_SIZE = 256


def post_json(endpoint: str, body: bytes) -> None:
    """POST the payload as `application/json`. The response body is read and dropped: only the send matters.

    `urllib.request` is imported HERE and not at the top, which is the one lazy import in this
    package and the one that earns it. `snakeorm/__init__` re-exports `snakeorm.debug`, which
    re-exports `export_report`, which lives in this module — so a module-level import would put an
    HTTP client (plus `http.client`, `email.*` and `ssl`, ~17 ms measured) into the startup of every
    application that uses the ORM, including the ones that never turn this channel on. The channel
    promises that switching it off costs nothing; an import is part of that promise.
    """
    import urllib.request

    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
        response.read()


def endpoint_from_env(environ: Mapping[str, str] | None = None) -> str:
    """The traces endpoint: the specific variable, then the generic one plus `/v1/traces`, then local."""
    env = _environ(environ)
    specific = env.get(TRACES_ENDPOINT_ENV_KEY, "").strip()
    if specific:
        return specific
    generic = env.get(ENDPOINT_ENV_KEY, "").strip()
    if generic:
        return f"{generic.rstrip('/')}{_TRACES_PATH}"
    return DEFAULT_ENDPOINT


def service_name_from_env(environ: Mapping[str, str] | None = None) -> str:
    """The service name (`OTEL_SERVICE_NAME`), or ours when the application did not declare one."""
    return (
        _environ(environ).get(SERVICE_NAME_ENV_KEY, "").strip() or DEFAULT_SERVICE_NAME
    )


def _environ(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    """The given mapping, or the real environment. Injected in tests, read for real everywhere else."""
    return os.environ if environ is None else environ


class OtelExporter:
    """Turns reports into OTLP spans and posts them, from a worker thread of its own.

    One per process (see `current_exporter`): one thread and one queue, not one per request.
    """

    __slots__ = (
        "_dropped",
        "_endpoint",
        "_failures",
        "_lock",
        "_parameter_keys",
        "_pending",
        "_queue",
        "_service_name",
        "_transport",
        "_warned",
        "_worker",
    )

    def __init__(
        self,
        *,
        endpoint: str,
        service_name: str,
        transport: Transport = post_json,
        queue_size: int = _DEFAULT_QUEUE_SIZE,
        parameter_keys: frozenset[str] = frozenset(),
    ) -> None:
        """`parameter_keys` names the query parameters to send, and there is NO environment variable for it.

        That omission is the decision: an environment variable is precisely the switch somebody
        flips in production by accident, and this one would send user data to a tracing backend. It
        takes an explicit line of code, key by key.
        """
        self._endpoint = endpoint
        self._service_name = service_name
        self._transport = transport
        self._parameter_keys = parameter_keys
        self._queue: queue.Queue[tuple[DebugReport, TraceContext | None] | None] = (
            queue.Queue(maxsize=queue_size)
        )
        self._lock = threading.Condition()
        self._pending = 0
        self._dropped = 0
        self._failures = 0
        self._warned = False
        self._worker: threading.Thread | None = None

    @property
    def endpoint(self) -> str:
        """Where the spans are posted."""
        return self._endpoint

    @property
    def service_name(self) -> str:
        """What the resource calls this service."""
        return self._service_name

    @property
    def dropped(self) -> int:
        """How many reports were discarded because the queue was full."""
        return self._dropped

    @property
    def failures(self) -> int:
        """How many sends the transport refused."""
        return self._failures

    def submit(self, report: DebugReport) -> None:
        """Queue a report and RETURN. Nothing is serialised or sent on the calling thread.

        The trace context is read HERE and not in the worker: it lives in a `ContextVar` belonging
        to the request's task, and a worker thread cannot see it.
        """
        item = (report, active_context())
        with self._lock:
            self._start_worker()
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self._dropped += 1
                return
            self._pending += 1

    def send_now(self, report: DebugReport, *, parent: TraceContext | None) -> None:
        """Build the payload and post it, synchronously. The worker's body, and the test's seam."""
        try:
            spans = spans_from_report(
                report, parent=parent, parameter_keys=self._parameter_keys
            )
            body = encode_payload(otlp_payload(spans, service_name=self._service_name))
            self._transport(self._endpoint, body)
        except (
            Exception
        ) as error:  # a collector that is down is not an application error
            self._record_failure(error)

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until the queue has drained. `True` if it did, `False` if the wait ran out."""
        with self._lock:
            return self._lock.wait_for(lambda: self._pending == 0, timeout=timeout)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Drain what is queued and stop the worker. Registered at exit for the process exporter."""
        self.flush(timeout)
        with self._lock:
            worker, self._worker = self._worker, None
        if worker is None:
            return
        self._queue.put(None)
        worker.join(timeout)

    def _start_worker(self) -> None:
        """Start the worker on first use. Daemon: a stuck send never keeps the process alive."""
        if self._worker is not None:
            return
        self._worker = threading.Thread(
            target=self._drain, name="snakeorm-otel", daemon=True
        )
        self._worker.start()

    def _drain(self) -> None:
        """Take reports off the queue and send them, one at a time, until the sentinel arrives."""
        while True:
            item = self._queue.get()
            if item is None:
                return
            report, parent = item
            try:
                self.send_now(report, parent=parent)
            finally:
                with self._lock:
                    self._pending -= 1
                    self._lock.notify_all()

    def _record_failure(self, error: Exception) -> None:
        """Count the failure and warn about the FIRST one, naming the endpoint and the reason."""
        with self._lock:
            self._failures += 1
            already_warned, self._warned = self._warned, True
        if already_warned:
            return
        warnings.warn(
            f"The debug channel 'otel' could not reach {self._endpoint}: {error}. "
            f"The spans of this request are lost; the following failures stay quiet.",
            SnakeWarning,
            stacklevel=2,
        )


_process_exporter: OtelExporter | None = None
_process_lock = threading.Lock()


def current_exporter() -> OtelExporter:
    """The process's exporter, built from the standard environment variables on first use."""
    global _process_exporter
    with _process_lock:
        if _process_exporter is None:
            _process_exporter = OtelExporter(
                endpoint=endpoint_from_env(), service_name=service_name_from_env()
            )
            atexit.register(_shutdown_process_exporter)
        return _process_exporter


def set_exporter(exporter: OtelExporter | None) -> None:
    """Install (or clear) the process exporter. `None` makes the next call build a fresh one."""
    global _process_exporter
    with _process_lock:
        _process_exporter = exporter


def _shutdown_process_exporter() -> None:
    """Drain whatever is queued before the interpreter goes away, so the last request is not lost."""
    exporter = _process_exporter
    if exporter is not None:
        exporter.shutdown()
