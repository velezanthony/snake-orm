"""The Django adapter, tested with DUCK-TYPED request/response —without installing Django—.

The middleware only uses `request.path`, `request.META`, and from the response `.content`,
`.get(header)` and `response[header] = value`. It gets handed doubles implementing exactly that, and
capture + delivery is verified without dragging in Django (only needed to serve the sidecar).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

from snakeorm.contrib.django import SnakeDebugMiddleware
from snakeorm.debug import CaptureDriver, SnakeDebugChannel, SnakeDebugConfig


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


class _FakeRequest:
    def __init__(
        self,
        path: str = "/x",
        query: str = "",
        csp_nonce: str | None = None,
        method: str = "GET",
    ) -> None:
        self.path = path
        self.method = method
        self.META = {"QUERY_STRING": query}
        # django-csp hangs one per request here; without it the attribute does not exist.
        if csp_nonce is not None:
            self.csp_nonce = csp_nonce


class _FakeResponse:
    """Minimal HttpResponse double: content, headers through `[]`/`get`."""

    def __init__(self, content: bytes, content_type: str = "application/json") -> None:
        self.content = content
        self.status_code = 200
        self._headers = {"Content-Type": content_type}

    def get(self, name: str, default: str = "") -> str:
        return self._headers.get(name, default)

    def __setitem__(self, name: str, value: str) -> None:
        self._headers[name] = value

    def __contains__(self, name: str) -> bool:
        return name in self._headers


def _get_response(driver: CaptureDriver, body: bytes = b'{"id":7}'):  # noqa: ANN202
    def view(request: _FakeRequest) -> _FakeResponse:
        driver.fetch_all("SELECT 1", ())
        return _FakeResponse(body)

    return view


def test_envelope_injected_into_json_with_trigger() -> None:
    """With the `envelope` channel and `?_debug=1`, the response's JSON content gains `snakeorm`."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugMiddleware(_get_response(driver))
    mw._channels = frozenset({SnakeDebugChannel.ENVELOPE})
    response = mw(_FakeRequest(query="_debug=1"))
    data = json.loads(response.content)
    assert data["id"] == 7
    assert data["snakeorm"]["count"] == 1


def test_timing_header_added() -> None:
    """The `timing` channel puts the Server-Timing header on the response."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugMiddleware(_get_response(driver))
    mw._channels = frozenset({SnakeDebugChannel.TIMING})
    response = mw(_FakeRequest())
    assert "Server-Timing" in response


def test_sidecar_sets_token_header() -> None:
    """The `sidecar` channel puts an X-Debug-Token on the response (the page is served separately)."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugMiddleware(_get_response(driver))
    mw._channels = frozenset({SnakeDebugChannel.SIDECAR})
    response = mw(_FakeRequest())
    assert "X-Debug-Token" in response


def test_content_length_resealed_after_ssr_panel() -> None:
    """Regression: after injecting the SSR panel, `Content-Length` is re-sealed to the REAL length.

    An inner middleware may set `Content-Length` with the HTML WITHOUT the panel. If the adapter does
    not re-seal it after lengthening the body, a real server truncates the response and the panel is
    lost (Django's test client does not catch it because it reads all of `.content`, ignoring
    `Content-Length`).
    """
    driver = CaptureDriver(_Inner())
    html = b"<html><body><h1>hola</h1></body></html>"

    def view(request: _FakeRequest) -> _FakeResponse:
        driver.fetch_all("SELECT 1", ())
        resp = _FakeResponse(html, content_type="text/html")
        resp["Content-Length"] = str(
            len(html)
        )  # an inner middleware sets it, WITHOUT the panel
        return resp

    mw = SnakeDebugMiddleware(view)
    mw._channels = frozenset({SnakeDebugChannel.SSR})
    response = mw(_FakeRequest())

    assert b"snake-debug-panel" in response.content  # the panel was injected...
    assert int(response.get("Content-Length")) == len(
        response.content
    )  # ...and Content-Length adds up


def _html_view(driver: CaptureDriver):  # noqa: ANN202
    def view(request: _FakeRequest) -> _FakeResponse:
        driver.fetch_all("SELECT 1", ())
        return _FakeResponse(
            b"<html><body><h1>hi</h1></body></html>", content_type="text/html"
        )

    return view


def _panel(mw: SnakeDebugMiddleware, request: _FakeRequest) -> bytes:
    """Run the middleware over an HTML view and return the delivered body."""
    mw._channels = frozenset({SnakeDebugChannel.SSR})
    body: bytes = mw(request).content
    return body


def test_ssr_panel_carries_the_configured_csp_nonce() -> None:
    """The `csp_nonce` of `SnakeDebugConfig` reaches the panel delivered by the middleware.

    Without it, an app with a strict CSP gets the panel blocked by the browser and no error
    anywhere: the config was declared and the adapter dropped it on the floor.
    """
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugMiddleware(_html_view(driver))
    mw._config = SnakeDebugConfig(csp_nonce="r4nd0m")
    assert b'<script type="module" nonce="r4nd0m">' in _panel(mw, _FakeRequest())


def test_ssr_panel_without_a_nonce_is_unchanged() -> None:
    """With no nonce configured, the delivered HTML carries no nonce at all (output unchanged)."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugMiddleware(_html_view(driver))
    mw._config = SnakeDebugConfig()
    body = _panel(mw, _FakeRequest())
    assert b"snake-debug-panel" in body
    assert b"nonce" not in body


def test_request_nonce_beats_the_configured_one() -> None:
    """`request.csp_nonce` (django-csp mints one per request) wins over the config's fixed one.

    A nonce fixed in the config is the same for every response, which is exactly what CSP does not
    want; when django-csp is mounted the per-request value is the one in the CSP header.
    """
    driver = CaptureDriver(_Inner())
    request = _FakeRequest(csp_nonce="per-request")
    mw = SnakeDebugMiddleware(_html_view(driver))
    mw._config = SnakeDebugConfig(csp_nonce="from-config")
    body = _panel(mw, request)
    assert b'nonce="per-request"' in body
    assert b"from-config" not in body


def test_the_request_nonce_is_escaped() -> None:
    """A nonce carrying HTML is escaped on its way into the attribute: no XSS through a header."""
    driver = CaptureDriver(_Inner())
    request = _FakeRequest(csp_nonce='"><script>x')
    mw = SnakeDebugMiddleware(_html_view(driver))
    body = _panel(mw, request)
    assert b'"><script>x' not in body
    assert b"&quot;&gt;&lt;script&gt;x" in body


def test_the_report_names_the_request_it_came_from() -> None:
    """The Django adapter fills the identity from `request.method`, `request.path` and the status."""
    driver = CaptureDriver(_Inner())
    mw = SnakeDebugMiddleware(_get_response(driver))
    mw._channels = frozenset({SnakeDebugChannel.ENVELOPE})

    response = mw(_FakeRequest(path="/posts/3", method="PUT"))

    request = json.loads(response.content)["snakeorm"]["request"]
    assert request["method"] == "PUT"
    assert request["path"] == "/posts/3"
    assert request["status"] == 200
    assert request["at"]
