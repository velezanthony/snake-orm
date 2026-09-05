"""Deliberate attacks on the debug subsystem: trying to BREAK IT before a user does.

Every test here is an edge case a naive adapter handles badly: streaming responses, non-ASCII content,
concurrency. If one of them blows up, it is a bug to be fixed, not a test to be loosened.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from snakeorm.contrib.asgi import SnakeDebugASGI
from snakeorm.contrib.deliver import inject_envelope
from snakeorm.contrib.django import SnakeDebugMiddleware
from snakeorm.contrib.sidecar import SidecarBuffer
from snakeorm.debug import (
    AsyncCaptureDriver,
    CaptureDriver,
    DebugReport,
    SnakeDebugChannel,
)


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


class _AsyncInner:
    async def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields whatever
        `fetch_all` returns. The degradation is written HERE, in plain sight, not done by the framework."""
        for row in await self.fetch_all(sql, params):
            yield row

    def __init__(self, n_rows: int) -> None:
        self._rows: list[tuple[object, ...]] = [(i,) for i in range(n_rows)]

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        await asyncio.sleep(0)  # yields control: it forces the tasks to interleave
        return self._rows

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        return 1

    @property
    def last_insert_id(self) -> int:
        """The id of the last INSERT. Test double: it writes nothing, so 0."""
        return 0

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def savepoint(self, name: str) -> None: ...
    async def release_savepoint(self, name: str) -> None: ...
    async def rollback_to_savepoint(self, name: str) -> None: ...
    async def close(self) -> None: ...


# --- ATTACK 1: Django with a streaming response (no .content) ---------------------------------


class _FakeStreamingResponse:
    """StreamingHttpResponse double: it has `.streaming=True` and does NOT have `.content`."""

    streaming = True
    status_code = 200

    def __init__(self) -> None:
        self._headers = {"Content-Type": "application/octet-stream"}

    def get(self, name: str, default: str = "") -> str:
        return self._headers.get(name, default)

    def __setitem__(self, name: str, value: str) -> None:
        self._headers[name] = value

    def __contains__(self, name: str) -> bool:
        return name in self._headers


class _FakeRequest:
    def __init__(self, query: str = "") -> None:
        self.path = "/download"
        self.META = {"QUERY_STRING": query}


def test_django_streaming_response_does_not_crash() -> None:
    """A streaming response does NOT have `.content`: the middleware must not blow up when touching it."""
    driver = CaptureDriver(_Inner())

    def view(request: _FakeRequest) -> _FakeStreamingResponse:
        driver.fetch_all("SELECT 1", ())
        return _FakeStreamingResponse()

    mw = SnakeDebugMiddleware(view)
    mw._channels = frozenset({SnakeDebugChannel.TIMING, SnakeDebugChannel.ENVELOPE})
    response = mw(_FakeRequest(query="_debug=1"))  # it must not raise AttributeError
    assert "Server-Timing" in response  # the headers do get delivered


# --- ATTACK 2: envelope with non-ASCII content -------------------------------------------------


def test_envelope_preserves_utf8() -> None:
    """A JSON body with accents must stay readable after injecting `snakeorm` (do not break the UTF-8)."""
    body = json.dumps({"name": "café con leche · ñandú"}, ensure_ascii=False).encode()
    out = inject_envelope(body, {"count": 1})
    data = json.loads(out)
    assert data["name"] == "café con leche · ñandú"
    assert data["snakeorm"] == {"count": 1}


def test_inject_envelope_empty_body_is_safe() -> None:
    """An empty body is not JSON: it is left untouched instead of blowing up."""
    assert inject_envelope(b"", {"count": 1}) == b""


# --- ATTACK 3: SidecarBuffer hammered from many threads -----------------------------------------


def test_sidecar_buffer_survives_concurrent_writers() -> None:
    """Many threads writing at once must not corrupt the buffer nor raise (WSGI is multi-threaded)."""
    buffer = SidecarBuffer(capacity=16)
    report = DebugReport.from_records([])
    errors: list[BaseException] = []

    def hammer(start: int) -> None:
        try:
            for i in range(200):
                buffer.store(f"t{start}-{i}", report)
                buffer.get(f"t{start}-{i}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(t,)) for t in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


# --- ATTACK 4: two concurrent ASGI requests must not mix their captures -------------------------


def test_asgi_concurrent_requests_do_not_mix_captures() -> None:
    """Two requests in parallel EACH capture their own: the contextvars do not get contaminated."""

    def make_app(rows: int) -> Any:
        driver = AsyncCaptureDriver(_AsyncInner(rows))

        async def app(scope: Any, receive: Any, send: Any) -> None:
            # Each app runs 'rows' queries; if the captures mixed, the counts would come out wrong.
            for _ in range(rows):
                await driver.fetch_all("SELECT 1", ())
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b"{}"})

        return app

    async def call(rows: int) -> dict[str, Any]:
        mw = SnakeDebugASGI(
            make_app(rows),
            channels=frozenset({SnakeDebugChannel.ENVELOPE}),
            production=False,
        )
        sent: list[dict[str, Any]] = []

        async def send(message: Any) -> None:
            sent.append(message)

        async def receive() -> Any:
            return {"type": "http.request"}

        scope = {
            "type": "http",
            "path": "/x",
            "query_string": b"_debug=1",
            "headers": [],
        }
        await mw(scope, receive, send)
        body = next(m["body"] for m in sent if m["type"] == "http.response.body")
        return json.loads(body)

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        # Three queries against seven, interleaved by the driver's await sleep(0).
        return await asyncio.gather(call(3), call(7))  # type: ignore[return-value]

    small, big = asyncio.run(run())
    assert small["snakeorm"]["count"] == 3
    assert big["snakeorm"]["count"] == 7


# --- ATTACK 5: two WSGI threads sharing one driver must not mix captures -----------------------


def test_wsgi_threaded_capture_isolation() -> None:
    """With a CaptureDriver SHARED between threads, each request counts only its own (contextvars)."""
    from snakeorm.contrib.wsgi import SnakeDebugWSGI

    driver = CaptureDriver(_Inner())  # ONE driver, shared by every thread
    results: dict[str, int] = {}
    errors: list[BaseException] = []

    def make_app(n: int) -> Any:
        def app(environ: dict[str, str], start_response: Any) -> list[bytes]:
            for _ in range(n):
                driver.fetch_all("SELECT 1", ())
            start_response("200 OK", [("Content-Type", "application/json")])
            return [b"{}"]

        return app

    def run(name: str, n: int) -> None:
        try:
            for _ in range(50):  # repeat to force the interleaving between threads
                mw = SnakeDebugWSGI(
                    make_app(n),
                    channels=frozenset({SnakeDebugChannel.ENVELOPE}),
                    production=False,
                )
                captured: dict[str, Any] = {}

                def start_response(status: str, headers: Any) -> None:
                    captured["_"] = status

                body = b"".join(
                    mw({"PATH_INFO": "/x", "QUERY_STRING": "_debug=1"}, start_response)
                )
                count = json.loads(body)["snakeorm"]["count"]
                if count != n:
                    results[name] = count  # a mix-up would leave a wrong count
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=("a", 3)),
        threading.Thread(target=run, args=("b", 11)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert results == {}  # no count came out wrong: nothing mixed between threads
