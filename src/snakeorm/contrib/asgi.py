"""ASGI adapter (FastAPI/Starlette): pure ASGI middleware that captures per request and delivers the debug by channel.

It does not import FastAPI, it serves the sidecar at `/__snake__/{token}` itself, and the SSR stays a no-op unless the app returns HTML.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

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

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_SIDECAR_PREFIX = "/__snake__/"


class SnakeDebugASGI:
    """ASGI middleware that captures the SQL and delivers the debug per `SNAKE_ORM_DEBUG`."""

    def __init__(
        self,
        app: ASGIApp,
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
        warn_unsupported(self._channels, SnakeWebFramework.FASTAPI)
        warn_unimplemented(self._channels)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entry point: it serves the sidecar, or captures and delivers the response's debug."""
        if scope["type"] != "http" or not self._channels:
            await self._app(scope, receive, send)
            return
        path: str = scope["path"]
        if (
            path.startswith(_SIDECAR_PREFIX)
            and SnakeDebugChannel.SIDECAR in self._channels
        ):
            await self._serve_sidecar(path, scope, send)
            return
        await self._capture_and_deliver(scope, receive, send)

    async def _serve_sidecar(self, path: str, scope: Scope, send: Send) -> None:
        """Serve `/__snake__/{token}`: the panel page, or the report as JSON if `Accept` asks.

        An ASGI scope keeps the headers as bytes pairs; WHAT to answer with them is decided in
        `serve_sidecar`, shared with the other two adapters.
        """
        page = serve_sidecar(
            self._buffer.get(path[len(_SIDECAR_PREFIX) :]),
            accept=_header(list(scope.get("headers", [])), b"accept"),
            language=self._config.language,
        )
        await _send_response(send, page.status, page.content_type, page.body)

    async def _capture_and_deliver(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Wrap the app in a scope, buffer its response and deliver it with the debug added."""
        start: Message = {}
        body = bytearray()

        async def capture_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                start.update(message)
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))

        t0 = perf_counter()
        at = datetime.now(UTC)  # the instant, taken where the wall clock starts
        with capture_queries() as collector:
            await self._app(scope, receive, capture_send)
        report = collector.report().with_wall_ms((perf_counter() - t0) * 1000)
        report = report.with_index_hints(index_advice(report, self._config))
        report = report.with_request(
            RequestInfo(
                method=scope.get("method", ""),
                path=scope.get("path", ""),
                status=int(start.get("status", 200)),
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

        headers: list[tuple[bytes, bytes]] = list(start.get("headers", []))
        content_type = _header(headers, b"content-type")
        new_body = transform_body(
            bytes(body),
            content_type,
            delivery,
            report,
            self._channels,
            self._config.language,
            # ASGI has no per-request seam for this: no spec field and no framework convention
            # holds a nonce, so the config's is the only one. FIXED for the process.
            self._config.csp_nonce,
            token=token,
        )
        for name, value in delivery.headers:
            headers.append((name.encode("latin1"), value.encode("latin1")))
        headers = _replace(headers, b"content-length", str(len(new_body)).encode())

        await send(
            {
                "type": "http.response.start",
                "status": start.get("status", 200),
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": new_body})


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    """The (decoded) value of a header by name, or an empty string if it is not there."""
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin1")
    return ""


def _replace(
    headers: list[tuple[bytes, bytes]], name: bytes, value: bytes
) -> list[tuple[bytes, bytes]]:
    """Return the headers with `name` set to `value` (removing any previous value)."""
    kept = [(key, val) for key, val in headers if key.lower() != name]
    kept.append((name, value))
    return kept


async def _send_response(
    send: Send, status: int, content_type: str, body: bytes
) -> None:
    """Emit a complete ASGI response (start + body) in a single body."""
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", content_type.encode("latin1")),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
