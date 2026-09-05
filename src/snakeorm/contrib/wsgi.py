"""WSGI adapter (Flask and any WSGI app): pure middleware that branches by `Content-Type` (the panel in HTML, `snakeorm` in JSON).

It does not import Flask; it also serves the sidecar at `/__snake__/{token}`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from time import perf_counter

from snakeorm.contrib.deliver import (
    allowed_channels,
    resolve_production,
    index_advice,
    plan_delivery,
    serve_sidecar,
    transform_body,
)
from snakeorm.contrib.sidecar import SidecarBuffer, new_token
from snakeorm.debug import (
    SnakeDebugChannel,
    SnakeDebugConfig,
    SnakeWebFramework,
    capture_queries,
    channels_from_env,
    export_report,
    RequestInfo,
    warn_unimplemented,
    warn_unsupported,
)

StartResponse = Callable[[str, list[tuple[str, str]]], object]
WSGIApp = Callable[[dict[str, str], StartResponse], Iterable[bytes]]

_SIDECAR_PREFIX = "/__snake__/"

# WSGI writes the status as a LINE, so the two the sidecar can answer are spelled here.
_STATUS_LINE = {200: "200 OK", 404: "404 Not Found"}


class SnakeDebugWSGI:
    """WSGI middleware that captures the SQL and delivers the debug per `SNAKE_ORM_DEBUG`."""

    def __init__(
        self,
        app: WSGIApp,
        *,
        channels: frozenset[SnakeDebugChannel] | None = None,
        production: bool | None = None,
        buffer: SidecarBuffer | None = None,
        config: SnakeDebugConfig | None = None,
    ) -> None:
        asked = channels_from_env() if channels is None else channels
        self._app = app
        self._config = config or SnakeDebugConfig.from_env()
        # The config is resolved BEFORE the channels because it is one of the two places the
        # environment can be declared, and `resolve_production` refuses rather than guessing when
        # neither says anything and a risky channel is on.
        self._channels = allowed_channels(
            asked, production=resolve_production(production, self._config, asked)
        )
        self._buffer = buffer or SidecarBuffer()
        warn_unsupported(self._channels, SnakeWebFramework.FLASK)
        warn_unimplemented(self._channels)

    def __call__(
        self, environ: dict[str, str], start_response: StartResponse
    ) -> Iterable[bytes]:
        """WSGI entry point: it serves the sidecar, or captures and delivers the response's debug."""
        path = environ.get("PATH_INFO", "")
        if (
            path.startswith(_SIDECAR_PREFIX)
            and SnakeDebugChannel.SIDECAR in self._channels
        ):
            return self._serve_sidecar(path, environ, start_response)
        if not self._channels:
            return self._app(environ, start_response)
        return self._capture_and_deliver(environ, start_response)

    def _serve_sidecar(
        self, path: str, environ: dict[str, str], start_response: StartResponse
    ) -> Iterable[bytes]:
        """Serve `/__snake__/{token}`: the panel page, or the report as JSON if `Accept` asks.

        `HTTP_ACCEPT` is where a WSGI environ keeps the header; WHAT to answer with it is decided in
        `serve_sidecar`, shared with the other two adapters.
        """
        page = serve_sidecar(
            self._buffer.get(path[len(_SIDECAR_PREFIX) :]),
            accept=environ.get("HTTP_ACCEPT", ""),
            language=self._config.language,
        )
        start_response(
            _STATUS_LINE[page.status],
            [
                ("Content-Type", page.content_type),
                ("Content-Length", str(len(page.body))),
            ],
        )
        return [page.body]

    def _capture_and_deliver(
        self, environ: dict[str, str], start_response: StartResponse
    ) -> Iterable[bytes]:
        """Wrap the app, buffer its response and deliver it with the debug added."""
        captured_status = "200 OK"
        captured_headers: list[tuple[str, str]] = []

        def capture_start(status: str, headers: list[tuple[str, str]]) -> object:
            nonlocal captured_status, captured_headers
            captured_status = status
            captured_headers = headers
            return None

        # Wall clock of the WHOLE request (app + DB + template): out of here comes the panel's
        # "en app" (wall - DB). It is measured around the app, not around the panel injection
        # (which is not part of the request).
        start = perf_counter()
        at = datetime.now(UTC)  # the instant, taken where the wall clock starts
        with capture_queries() as collector:
            body = b"".join(self._app(environ, capture_start))
        report = collector.report().with_wall_ms((perf_counter() - start) * 1000)
        report = report.with_index_hints(index_advice(report, self._config))
        report = report.with_request(
            RequestInfo(
                method=environ.get("REQUEST_METHOD", ""),
                path=environ.get("PATH_INFO", ""),
                status=_status_code(captured_status),
                at=at,
            )
        )

        token = None
        if SnakeDebugChannel.SIDECAR in self._channels:
            token = new_token()
            self._buffer.store(token, report)
        # The `otel` channel: OUT of `plan_delivery`, which is a pure function that answers
        # `(headers, envelope)` — two things that change the response, which a network send is not.
        # Shared the same way `index_advice` is.
        export_report(report, self._channels)
        delivery = plan_delivery(report, self._channels, token=token)

        content_type = next(
            (value for key, value in captured_headers if key.lower() == "content-type"),
            "",
        )
        new_body = transform_body(
            body,
            content_type,
            delivery,
            report,
            self._channels,
            self._config.language,
            # WSGI has no per-request seam for this: `environ` carries no nonce convention, so the
            # config's is the only one. It is FIXED for the process; a strict CSP wants one per
            # response, which here means the app must repeat it in its own header.
            self._config.csp_nonce,
            token=token,
        )
        headers = [
            (key, value)
            for key, value in captured_headers
            if key.lower() != "content-length"
        ]
        headers.extend(delivery.headers)
        headers.append(("Content-Length", str(len(new_body))))

        start_response(captured_status, headers)
        return [new_body]


def _status_code(status: str) -> int:
    """The number out of a WSGI status line (`"404 Not Found"` -> `404`); 0 if it is not one."""
    code, _, _ = status.partition(" ")
    return int(code) if code.isdigit() else 0
