"""The PURE delivery core: what gets done to a response in order to serve the debug.

All the hard logic lives here —which headers, when to inject the envelope, the production gate, the
per-request trigger— in pure, testable functions. The adapters (ASGI/WSGI/Django) are just plumbing
that calls into this: that way the logic is tested without installing three web frameworks.
"""

from __future__ import annotations

import json

from snakeorm.debug import (
    RISKY_CHANNELS,
    DebugReport,
    QueryKind,
    QueryRecord,
    SnakeDebugChannel,
)
from snakeorm.contrib.deliver import (
    allowed_channels,
    inject_envelope,
    inject_panel,
    plan_delivery,
    transform_body,
)


def _report() -> DebugReport:
    return DebugReport.from_records(
        [
            QueryRecord(
                n=1,
                sql="SELECT 1",
                params=(),
                duration_ms=2.0,
                rows=1,
                kind=QueryKind.SELECT,
            )
        ]
    )


def test_allowed_channels_strips_every_risky_channel_in_production() -> None:
    """In production EVERY risky channel drops, even if asked for — derived, not listed here.

    It used to name `envelope` and `sidecar` by hand, which is a copy of the set it is checking:
    while `ssr` was missing from `RISKY_CHANNELS` this test was green over the same hole, asserting
    that the two channels it happened to know about got dropped. Feeding it the whole enum and
    deriving the expectation means a channel added to either side cannot pass unnoticed.
    """
    asked = frozenset(SnakeDebugChannel)

    assert allowed_channels(asked, production=True) == asked - RISKY_CHANNELS
    assert SnakeDebugChannel.SSR not in allowed_channels(asked, production=True)


def test_allowed_channels_leaves_everything_alone_outside_production() -> None:
    """Out of production nothing is filtered: that is the whole point of the flag.

    The floor under the test above — without it, `allowed_channels` returning an empty set would
    satisfy the production half and nobody would notice the debug had stopped working in dev.
    """
    asked = frozenset(SnakeDebugChannel)

    assert allowed_channels(asked, production=False) == asked


def test_allowed_channels_keeps_all_in_dev() -> None:
    """In development, whatever was asked for is respected."""
    asked = frozenset({SnakeDebugChannel.ENVELOPE, SnakeDebugChannel.TIMING})
    assert allowed_channels(asked, production=False) == asked


def test_plan_delivery_timing_header() -> None:
    """The `timing` channel adds the Server-Timing header."""
    delivery = plan_delivery(_report(), frozenset({SnakeDebugChannel.TIMING}))
    names = dict(delivery.headers)
    assert "Server-Timing" in names


def test_plan_delivery_envelope_follows_the_channel() -> None:
    """The envelope is planned IF the `envelope` channel was asked for: the channel is the switch."""
    assert plan_delivery(_report(), frozenset()).envelope is None
    with_ch = plan_delivery(_report(), frozenset({SnakeDebugChannel.ENVELOPE}))
    assert with_ch.envelope is not None


def test_plan_delivery_sidecar_token() -> None:
    """The `sidecar` channel adds the X-Debug-Token header when there is a token."""
    delivery = plan_delivery(
        _report(),
        frozenset({SnakeDebugChannel.SIDECAR}),
        token="abc123",
    )
    assert ("X-Debug-Token", "abc123") in delivery.headers


def test_inject_envelope_adds_snakeorm_key_to_a_json_object() -> None:
    """If the body is already an object, `snakeorm` is added as a sibling: it keeps its shape, no wrapping."""
    body = json.dumps({"id": 7}).encode()
    out = json.loads(inject_envelope(body, {"count": 1}))
    assert out["id"] == 7  # the object keeps its top-level keys
    assert out["snakeorm"] == {"count": 1}


def test_inject_envelope_wraps_a_json_array() -> None:
    """A top-level ARRAY is no longer left without debug: it gets wrapped in `{data, snakeorm}`.

    It is the gap the old envelope (injecting a key into the object) could not cover: you cannot add
    a key to an array, but you can wrap it.
    """
    body = json.dumps([1, 2, 3]).encode()
    out = json.loads(inject_envelope(body, {"count": 1}))
    assert out["data"] == [1, 2, 3]
    assert out["snakeorm"] == {"count": 1}


def test_inject_envelope_leaves_non_json_bodies_untouched() -> None:
    """A body that is not JSON (plain text) is left untouched: there is nowhere to hang the envelope."""
    assert inject_envelope(b"no soy json", {"count": 1}) == b"no soy json"


def test_inject_panel_before_body_tag() -> None:
    """`inject_panel` puts the HTML panel right before `</body>`."""
    out = inject_panel(b"<html><body>hola</body></html>", _report())
    assert out.index(b"snake-debug-panel") < out.index(b"</body>")


def test_transform_body_forwards_the_csp_nonce_to_the_panel() -> None:
    """`transform_body` hands the nonce down to the panel's mounting script.

    It is the only path the three adapters go through to render the panel, so a nonce that stops
    here never reaches a middleware-delivered page.
    """
    out = transform_body(
        b"<html><body>hi</body></html>",
        "text/html",
        plan_delivery(_report(), frozenset({SnakeDebugChannel.SSR})),
        _report(),
        frozenset({SnakeDebugChannel.SSR}),
        csp_nonce="r4nd0m",
    )
    assert b'<script type="module" nonce="r4nd0m">' in out


def test_transform_body_without_a_nonce_is_unchanged() -> None:
    """With no nonce the panel comes out byte for byte as before: the parameter adds nothing."""
    args = (
        b"<html><body>hi</body></html>",
        "text/html",
        plan_delivery(_report(), frozenset({SnakeDebugChannel.SSR})),
        _report(),
        frozenset({SnakeDebugChannel.SSR}),
    )
    assert transform_body(*args, csp_nonce=None) == transform_body(*args)
    assert b"nonce" not in transform_body(*args)


def test_inject_panel_leaves_an_html_fragment_untouched() -> None:
    """An HTML response with no `</body>` gets NOTHING in its body: the fragment comes back intact.

    A fragment is what HTMX/Alpine swap into a page that is already rendered. Appending the panel
    to it hands the application TWO top-level nodes where it asked for one: with `innerHTML` it
    changes what `:last-child` means, with `outerHTML` the parent gains a child, and under
    `hx-select` the real content can be the half that gets dropped. A debug tool does not reshape
    somebody else's DOM.
    """
    fragment = b'<div id="rows"><tr><td>7</td></tr></div>'

    assert inject_panel(fragment, _report()) == fragment


def test_transform_body_leaves_an_html_fragment_untouched() -> None:
    """The whole delivery path respects the fragment: `text/html` with no `</body>` is not rewritten."""
    fragment = b"<li>one row</li>"

    out = transform_body(
        fragment,
        "text/html; charset=utf-8",
        plan_delivery(_report(), frozenset({SnakeDebugChannel.SSR})),
        _report(),
        frozenset({SnakeDebugChannel.SSR}),
    )

    assert out == fragment


def test_a_fragment_still_gets_its_headers() -> None:
    """What a fragment DOES carry is headers, and the channels are what govern them.

    `</body>` is the discriminator, and it is library-agnostic on purpose: `HX-Request` would tie
    the ORM to HTMX, and Alpine (or a plain `fetch`) never sends it. The headers do not depend on
    the body at all, so the fragment keeps its `Server-Timing` and its `X-Debug-Token`.
    """
    channels = frozenset({SnakeDebugChannel.TIMING, SnakeDebugChannel.SIDECAR})
    delivery = plan_delivery(_report(), channels, token="abc123")

    names = dict(delivery.headers)

    assert 'desc="1 queries"' in names["Server-Timing"]
    assert names["X-Debug-Token"] == "abc123"


def test_a_fragment_gets_no_headers_from_channels_that_are_off() -> None:
    """With the channels off, the fragment gets no headers either: the channel is the only switch."""
    assert plan_delivery(_report(), frozenset({SnakeDebugChannel.SSR})).headers == ()


def test_transform_body_hands_the_panel_its_token_and_channels() -> None:
    """The delivered panel stamps its own token and knows whether the `envelope` channel is on.

    This is the only path the three adapters take to render the panel, so anything that stops here
    never reaches a middleware-delivered page — the same failure the nonce had.
    """
    channels = frozenset({SnakeDebugChannel.SSR})
    out = transform_body(
        b"<html><body>hi</body></html>",
        "text/html",
        plan_delivery(_report(), channels, token="abc123"),
        _report(),
        channels,
        token="abc123",
    )

    assert b'data-token="abc123"' in out
    # SSR without ENVELOPE: the history tab says the channel it needs is missing.
    assert b'<div class="snk-view snk-view-history" data-envelope="off">' in out
