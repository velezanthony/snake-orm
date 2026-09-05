"""The WSGI and ASGI middleware over the THREE engines, with a real session behind them.

The adapters were exercised over a FAKE driver, which is the right way to test a middleware's own
mechanics — status, headers, the envelope's shape. What it cannot say is whether the panel a user
gets carries the statements a REAL engine ran, and that is the whole product of the layer.

The ASGI half also pins the one thing that broke in production and looked like nothing: a header
must stay ASCII. ASGI encodes headers as latin-1, so a non-ASCII byte in one is not a cosmetic
problem — it raised inside Starlette's test client, which is how it was found.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable, Iterator

import pytest

from snakeorm import (
    SnakeQuery,
    SnakeSession,
    SnakeColumn,
    SnakeModel,
    snake_int,
    snake_model,
    snake_str,
)
from snakeorm.contrib.asgi import Message, Receive, Scope, Send, SnakeDebugASGI
from snakeorm.contrib.wsgi import SnakeDebugWSGI
from snakeorm.debug import CaptureDriver, SnakeDebugChannel
from snakeorm.drivers.base import SnakeDriver
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@snake_model(table="cmw_widgets")
class Widget(SnakeModel):
    """Something the fake application reads, so the panel has a statement to show."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=40)


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three sessions wrapped in the capture driver the adapters rely on."""

    def wrap(engine: str, driver: SnakeDriver) -> SnakeDriver:
        return CaptureDriver(driver, system=engine)

    with three_sessions([Widget], wrap=wrap) as sessions:
        for session in sessions.values():
            session.add(Widget(id=1, name="tuerca"))
            session.commit()
        yield sessions


def _json_app(session: SnakeSession) -> Callable[..., Iterable[bytes]]:
    """A minimal WSGI application that READS through the ORM and answers JSON."""

    def app(
        environ: dict[str, str], start_response: Callable[..., object]
    ) -> Iterable[bytes]:
        rows = session.all(SnakeQuery(Widget))
        body = json.dumps({"names": [row.name for row in rows]}).encode()
        start_response("200 OK", [("Content-Type", "application/json")])
        return [body]

    return app


def _run_wsgi(middleware: SnakeDebugWSGI) -> tuple[list[tuple[str, str]], bytes]:
    """Drives the middleware as a WSGI server would, collecting headers and body."""
    captured: list[tuple[str, str]] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured.extend(headers)

    body = b"".join(
        middleware({"PATH_INFO": "/x", "QUERY_STRING": "_debug=1"}, start_response)
    )
    return captured, body


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_envelope_carries_what_the_real_engine_ran(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The panel a user gets must describe the statements that actually ran, on any engine.

    Over a fake driver this test would pass with the envelope describing nothing at all — the count
    is what makes it an assertion.
    """
    middleware = SnakeDebugWSGI(
        _json_app(engines[engine]),
        channels=frozenset({SnakeDebugChannel.ENVELOPE}),
        production=False,
    )

    _, body = _run_wsgi(middleware)
    payload = json.loads(body)

    assert payload["names"] == ["tuerca"]
    assert payload["snakeorm"]["count"] >= 1, (
        f"{engine}: the envelope reports no statement for a request that read the database"
    )


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_timing_header_is_ascii_on_every_engine(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """A header has to survive latin-1, and that is not pedantry: it broke a test client once.

    The engine matters here because the header is built from a report whose contents come from the
    engine — a name or a unit sneaking in non-ASCII would only show up on the engine that produced
    it.
    """
    middleware = SnakeDebugWSGI(
        _json_app(engines[engine]), channels=frozenset({SnakeDebugChannel.TIMING})
    )

    headers, _ = _run_wsgi(middleware)
    timing = [value for name, value in headers if name.lower() == "server-timing"]

    assert timing, f"{engine}: no Server-Timing header came back"
    timing[0].encode("latin-1")


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_asgi_adapter_answers_the_same_way(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The async twin of the adapter, over the same real session.

    The application is synchronous on purpose: what is under test is the MIDDLEWARE's async path,
    not the session's, and mixing both would leave a failure ambiguous.
    """
    session = engines[engine]
    received: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        rows = session.all(SnakeQuery(Widget))
        body = json.dumps({"names": [row.name for row in rows]}).encode()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": body})

    async def collect(message: Message) -> None:
        received.append(message)

    async def incoming() -> Message:
        return {"type": "http.request"}

    middleware = SnakeDebugASGI(app, channels=frozenset({SnakeDebugChannel.TIMING}))
    scope: Scope = {
        "type": "http",
        "path": "/x",
        "query_string": b"_debug=1",
        "headers": [],
    }

    asyncio.run(middleware(scope, incoming, collect))

    start = next(m for m in received if m["type"] == "http.response.start")
    headers: list[tuple[bytes, bytes]] = start["headers"]

    assert headers, f"{engine}: the ASGI adapter added no header at all"
    for name, value in headers:
        # latin-1 and not utf-8: it is what the ASGI spec encodes headers with, so a non-ASCII byte
        # here raises inside the server rather than showing up as a mangled string.
        name.decode("latin-1")
        value.decode("latin-1")
