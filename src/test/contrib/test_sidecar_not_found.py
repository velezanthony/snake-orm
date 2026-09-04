"""The 404 of an expired sidecar token: ONE body, and the three adapters all serve that one.

`/__snake__/{token}` is a URL a person opens in a browser, so its 404 body is not an internal detail:
it is the only thing the panel gets to say once the report has been evicted from the ring buffer.
The three adapters answered `b"token desconocido"` — Spanish, in `contrib/`, outside the single
bilingual exemption. That exemption covers the debug PANEL, where the language is a feature
served by `SnakeDebugLanguage`; these adapters have no selector to serve, which is exactly why
`debug/channel.py` lost its own cover.

`debug/channel.py` is also the precedent for the FIX: its Spanish `SnakeConfigError` was not merely
translated, it was made to name what happened and what to do about it. The same shape is asserted
here, and the three adapters are compared against ONE constant so a later edit cannot move one of
them and leave the other two behind.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, MutableMapping
from typing import Any

import pytest

from snakeorm.contrib.asgi import SnakeDebugASGI
from snakeorm.contrib.deliver import SIDECAR_UNKNOWN_TOKEN_BODY
from snakeorm.contrib.wsgi import SnakeDebugWSGI
from snakeorm.debug import SnakeDebugChannel

_CHANNELS = frozenset({SnakeDebugChannel.SIDECAR})
_GONE = "/__snake__/a-token-nobody-ever-stored"


def _unreachable_wsgi(
    environ: dict[str, str], start_response: object
) -> Iterable[bytes]:
    """WSGI app that must never run: the sidecar path answers before reaching it."""
    raise AssertionError("the sidecar path must not fall through to the wrapped app")


async def _unreachable_asgi(scope: Any, receive: Any, send: Any) -> None:
    """ASGI app that must never run, for the same reason."""
    raise AssertionError("the sidecar path must not fall through to the wrapped app")


def _wsgi_body() -> bytes:
    """The 404 body the WSGI adapter writes for a token that is gone."""
    middleware = SnakeDebugWSGI(_unreachable_wsgi, channels=_CHANNELS, production=False)
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> object:
        captured["status"] = status
        return None

    body = b"".join(middleware({"PATH_INFO": _GONE}, start_response))
    assert captured["status"] == "404 Not Found"
    return body


def _asgi_body() -> bytes:
    """The 404 body the ASGI adapter writes for a token that is gone."""
    middleware = SnakeDebugASGI(_unreachable_asgi, channels=_CHANNELS, production=False)
    messages: list[dict[str, Any]] = []

    async def send(message: MutableMapping[str, Any]) -> None:
        messages.append(dict(message))

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "http.request", "body": b""}

    asyncio.run(middleware({"type": "http", "path": _GONE}, receive, send))
    start = next(item for item in messages if item["type"] == "http.response.start")
    assert start["status"] == 404
    return b"".join(
        bytes(item.get("body", b""))
        for item in messages
        if item["type"] == "http.response.body"
    )


def _django_body() -> bytes:
    """The 404 body the Django adapter hands to `HttpResponseNotFound`.

    Django's `HttpResponse` refuses to be built without configured settings, and configuring them
    globally would leak into every other test in the run. The adapter imports the class lazily
    INSIDE the method, so replacing the attribute on `django.http` is enough to read the body it
    passes — and it keeps this test from being the one that configures Django for the whole suite.
    """
    import django.http

    from snakeorm.contrib.django import SnakeDebugMiddleware

    recorded: list[bytes] = []

    class _NotFound:
        status_code = 404

        def __init__(self, content: bytes) -> None:
            recorded.append(bytes(content))

    original = django.http.HttpResponseNotFound
    django.http.HttpResponseNotFound = _NotFound  # type: ignore[misc, assignment]
    try:

        def unreachable(request: object) -> object:
            raise AssertionError("the sidecar path must not fall through to the view")

        middleware = SnakeDebugMiddleware(unreachable)
        middleware._channels = _CHANNELS

        class _Request:
            path = _GONE

        response = middleware(_Request())
        assert response.status_code == 404
    finally:
        django.http.HttpResponseNotFound = original  # type: ignore[misc]
    return recorded[0]


@pytest.mark.parametrize(
    "body_of",
    [_wsgi_body, _asgi_body, _django_body],
    ids=["wsgi", "asgi", "django"],
)
def test_every_adapter_serves_the_same_unknown_token_body(
    body_of: object,
) -> None:
    """WSGI, ASGI and Django answer an expired token with the SAME body.

    Each is compared against one shared constant rather than against the others' current text: that
    is what stops a later edit from moving one adapter on its own.
    """
    assert callable(body_of)
    assert body_of() == SIDECAR_UNKNOWN_TOKEN_BODY


def test_the_unknown_token_body_says_what_happened_and_what_to_do() -> None:
    """The body is not a bare label: it explains that the report expired and how to get a fresh one.

    `debug/channel.py` set the shape — an unknown channel does not merely fail, it names the channel
    and lists the valid ones. Whoever lands here has a stale browser tab, and the two-word body this
    used to carry did not tell them that.
    """
    assert SIDECAR_UNKNOWN_TOKEN_BODY == (
        b"Unknown debug token: this report is no longer buffered. The sidecar keeps only the most "
        b"recent reports, so reload the page that produced it to get a fresh token."
    )
