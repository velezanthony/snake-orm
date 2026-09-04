"""PURE core of the debug delivery: headers, envelope and the production gate, in pure functions.

The adapters (ASGI/WSGI/Django) are thin plumbing that calls in here: the logic gets tested and is not duplicated; only the irreducible difference (ASGI ≠ WSGI) stays at the edge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from snakeorm.advisor import index_hints_from_records
from snakeorm.core.exceptions import SnakeConfigError
from snakeorm.debug import (
    PRODUCTION_ENV_KEY,
    RISKY_CHANNELS,
    DebugReport,
    SnakeDebugChannel,
    SnakeDebugConfig,
    SnakeDebugLanguage,
    render_report_html,
    render_report_page,
)
from snakeorm.migration import current_schema


SIDECAR_UNKNOWN_TOKEN_BODY = (
    b"Unknown debug token: this report is no longer buffered. The sidecar keeps only the most "
    b"recent reports, so reload the page that produced it to get a fresh token."
)
"""The 404 body for `/__snake__/{token}` when the report is gone, for the THREE adapters.

It lives here and not in each adapter for the same reason everything else in this module does: three
copies of one sentence drift, and this one had already drifted into Spanish (`token desconocido`) in
all three at once — a body a person reads in their browser, in `contrib/`, outside the single
bilingual exemption, which covers the debug PANEL. These adapters serve no `SnakeDebugLanguage`
selector, which is precisely the reasoning that took `debug/channel.py` out of that exemption.

And it says what happened, not just that something did: whoever lands here is holding a stale tab,
and the two words it used to carry never told them to reload.
"""


@dataclass(frozen=True, slots=True)
class SidecarPage:
    """What `/__snake__/{token}` answers: the status, the content type and the body.

    One shape for the three adapters, so the decision of WHAT to answer is taken once and each of
    them is left with the only thing that really differs: how its protocol writes a response.
    """

    status: int
    content_type: str
    body: bytes


def serve_sidecar(
    report: DebugReport | None,
    *,
    accept: str = "",
    language: SnakeDebugLanguage = SnakeDebugLanguage.EN,
) -> SidecarPage:
    """Answer a sidecar token: the panel page to a browser, the report itself to `Accept: application/json`.

    The URL has TWO readers. A person opens it and wants the panel. The history tab holds a token
    off a response whose body it never sees —an HTML fragment carries its report in the headers— and
    wants the report; handing it a document that embeds the whole panel would make it parse markup
    to recover data the server already has as a dictionary.

    The JSON body is `DebugReport.to_dict()`, the very dictionary the `envelope` channel hangs off
    JSON responses, so the tab reads ONE shape whichever channel brought it.

    The 404 does NOT negotiate: there is one sentence for an evicted report, and a second
    serialisation of it would be a second wording to keep in step.
    """
    if report is None:
        return SidecarPage(404, "text/plain; charset=utf-8", SIDECAR_UNKNOWN_TOKEN_BODY)
    if "application/json" in accept:
        body = json.dumps(report.to_dict(), ensure_ascii=False).encode()
        return SidecarPage(200, "application/json; charset=utf-8", body)
    page = render_report_page(report, language=language).encode()
    return SidecarPage(200, "text/html; charset=utf-8", page)


def resolve_production(
    explicit: bool | None,
    config: SnakeDebugConfig,
    channels: frozenset[SnakeDebugChannel],
) -> bool:
    """WHERE this process runs: the explicit argument, then the config, then a REFUSAL.

    The order is deliberate. Somebody already passing `production=` keeps the last word; otherwise
    the config answers (from code or from `SNAKE_ORM_PRODUCTION`); and if nobody said anything, the
    answer depends on what is at stake. With no risky channel on there is no SQL to leak, so silence
    resolves to development and costs nothing. With one on, the middleware refuses to start.

    What is NOT here is a default of `False`, and that absence is the whole point. The channels read
    themselves out of the environment while this one sat next to them defaulting to the permissive
    answer — two switches for one decision, and the manual one wrong-way-round. The project's own
    rule is that a typo never falls back to a default; this is that rule applied to the switch that
    decides whether the SQL goes out on the response.
    """
    if explicit is not None:
        return explicit
    if config.production is not None:
        return config.production
    risky = channels & RISKY_CHANNELS
    if risky:
        names = ", ".join(sorted(channel.value for channel in risky))
        raise SnakeConfigError(
            f"These debug channels hand the SQL to whoever asked ({names}) and nothing declares "
            f"whether this is production. Set {PRODUCTION_ENV_KEY}=true|false, or pass "
            f"production=True/False (or SnakeDebugConfig(production=...)). There is no default: "
            f"guessing 'development' here is how a deploy serves its statements, with the values "
            f"already substituted, to anyone who asks for a page."
        )
    return False


def allowed_channels(
    channels: frozenset[SnakeDebugChannel],
    *,
    production: bool,
) -> frozenset[SnakeDebugChannel]:
    """Filter the channels by environment: in production the ones exposing SQL are dropped, even if requested (attack surface)."""
    if not production:
        return channels
    return channels - RISKY_CHANNELS


def index_advice(
    report: DebugReport, config: SnakeDebugConfig
) -> tuple[tuple[str, str, float], ...]:
    """Index suggestions for the SLOW queries of the report: the advisor over the SQL + the metadata.

    It only looks at queries above `config.advise_min_ms` (the user's threshold, or 10 ms by
    default): a fast query over an unindexed column does not deserve an index. Empty if nothing slow
    filtered.
    """
    if not report.records:
        return ()
    rows = [(record.sql, record.duration_ms) for record in report.records]
    return tuple(
        index_hints_from_records(rows, current_schema(), min_ms=config.advise_min_ms)
    )


@dataclass(frozen=True, slots=True)
class Delivery:
    """What to do with the response: headers to add and, if applicable, the `snakeorm` block to inject."""

    headers: tuple[tuple[str, str], ...]
    envelope: dict[str, object] | None


def plan_delivery(
    report: DebugReport,
    channels: frozenset[SnakeDebugChannel],
    *,
    token: str | None = None,
) -> Delivery:
    """Decide headers and envelope from the channels that are on (framework-agnostic).

    The envelope comes out IF the `envelope` channel was requested: the channel itself is the
    switch (if you declare it in `DEBUG`, you want it). In production `allowed_channels` already
    removes it, so nothing leaks.
    """
    headers: list[tuple[str, str]] = []
    if SnakeDebugChannel.TIMING in channels:
        headers.append(("Server-Timing", report.to_server_timing()))
    if SnakeDebugChannel.SIDECAR in channels and token is not None:
        headers.append(("X-Debug-Token", token))
    envelope = report.to_dict() if SnakeDebugChannel.ENVELOPE in channels else None
    return Delivery(tuple(headers), envelope)


def inject_envelope(body: bytes, envelope: dict[str, object]) -> bytes:
    """Hang the debug (`snakeorm`) off the JSON body, without corrupting it or over-nesting it.

    If the body is already an OBJECT, it is enough to ADD the `snakeorm` key as a sibling (it keeps
    its shape, with no extra wrapping). If it is an ARRAY or a scalar —where you cannot put a key—
    it gets wrapped in `{"data": <response>, "snakeorm": <debug>}`. A non-JSON body is left intact.
    """
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if isinstance(data, dict):
        data["snakeorm"] = (
            envelope  # already an object: the key fits as a sibling, no wrapping
        )
    else:
        data = {"data": data, "snakeorm": envelope}  # array/scalar: must be wrapped
    # `ensure_ascii=False` so the accents do not get re-escaped to `\uXXXX`: it preserves the UTF-8
    # as it is (the way Starlette does) and does not double the size of a response with non-ASCII
    # text.
    return json.dumps(data, ensure_ascii=False).encode()


def inject_panel(
    body: bytes,
    report: DebugReport,
    language: SnakeDebugLanguage = SnakeDebugLanguage.EN,
    csp_nonce: str | None = None,
    *,
    token: str | None = None,
    channels: frozenset[SnakeDebugChannel] | None = None,
) -> bytes:
    """Insert the HTML panel right before `</body>`; a body with no such tag comes back INTACT.

    No `</body>` means a FRAGMENT (an HTMX/Alpine swap), and a fragment gets nothing in its body.
    Appending anything returns two top-level nodes where the application asked for one, which
    changes `:last-child` under `innerHTML`, adds a child under `outerHTML` and can be dropped by
    `hx-select`. The fragment's debug travels in the headers instead. `</body>` is the
    discriminator on purpose: `HX-Request` would tie this to one library.

    `csp_nonce` travels through to the mounting script. An application with a strict
    Content-Security-Policy generates one per response and hands it in; without it the panel is
    injected exactly as before, and under `script-src 'self'` the browser drops it in silence.
    """
    marker = b"</body>"
    if marker not in body:
        return body
    panel = render_report_html(
        report,
        language=language,
        csp_nonce=csp_nonce,
        token=token,
        channels=channels,
    ).encode()
    return body.replace(marker, panel + marker, 1)


def transform_body(
    body: bytes,
    content_type: str,
    delivery: Delivery,
    report: DebugReport,
    channels: frozenset[SnakeDebugChannel],
    language: SnakeDebugLanguage = SnakeDebugLanguage.EN,
    csp_nonce: str | None = None,
    *,
    token: str | None = None,
) -> bytes:
    """Rewrite the body by `Content-Type` (envelope in JSON, panel in HTML): one adapter serves a hybrid app without wiring two things.

    `csp_nonce` and `token` ride alongside `language`: this is the ONLY path the three adapters take
    to render the panel, so anything that does not travel here never reaches a middleware-delivered
    page. The channels travel too — the history tab reads them to say `envelope` is missing.
    """
    if delivery.envelope is not None and "application/json" in content_type:
        return inject_envelope(body, delivery.envelope)
    if SnakeDebugChannel.SSR in channels and "text/html" in content_type:
        return inject_panel(
            body, report, language, csp_nonce, token=token, channels=channels
        )
    return body
