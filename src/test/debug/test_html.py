"""The HTML renderer of the debug panel: a pure `DebugReport -> str` function.

It lives in the core (not in a contrib) because TWO consumers reuse it: the SSR injection
(Django/Flask) and the sidecar's standalone page (FastAPI). And since it paints SQL and params that
may come from anywhere, EVERYTHING is escaped: a `<script>` in a value cannot turn into XSS.
"""

from __future__ import annotations

from snakeorm.debug import DebugReport, QueryKind, QueryRecord, render_report_html


def _report(*records: QueryRecord) -> DebugReport:
    return DebugReport.from_records(records)


def _rec(n: int, sql: str, *, params: tuple[object, ...] = ()) -> QueryRecord:
    return QueryRecord(
        n=n, sql=sql, params=params, duration_ms=1.0, rows=1, kind=QueryKind.SELECT
    )


def test_panel_contains_summary_and_sql() -> None:
    """The panel includes the summary and the text of every SQL."""
    html = render_report_html(_report(_rec(1, "SELECT id FROM users")))
    assert "1 queries" in html
    assert "SELECT id FROM users" in html


def test_panel_escapes_sql_to_prevent_xss() -> None:
    """A `<script>` inside the SQL is escaped: it never comes out as a live tag."""
    html = render_report_html(_report(_rec(1, "SELECT '<script>alert(1)</script>'")))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_panel_escapes_params_to_prevent_xss() -> None:
    """A malicious param is escaped too: the value comes from outside, it is not to be trusted."""
    html = render_report_html(
        _report(_rec(1, "SELECT %s", params=("<img src=x onerror=1>",)))
    )
    assert "<img src=x onerror=1>" not in html
    assert "&lt;img" in html


def test_panel_shows_warnings() -> None:
    """When there are warnings (N+1), the panel shows them."""
    dup = [_rec(i, "SELECT * FROM cars WHERE id=%s", params=(i,)) for i in range(1, 4)]
    html = render_report_html(_report(*dup))
    assert "N+1" in html


def test_the_panel_can_carry_a_csp_nonce() -> None:
    """With a nonce declared, the mounting script carries it and survives a strict CSP.

    THE FAILURE IT CLOSES, and it is a silent one: the panel is a `<template>` plus an inline
    `<script type="module">` that mounts it into a shadow root. Under `script-src 'self'` — no
    `unsafe-inline`, no nonce, which is what a hardened app ships — the browser blocks that script
    and the template never mounts. Nothing renders, nothing errors on the server, and the panel is
    simply gone. Half of what this file emits is inside that template, so "gone" means all of it.

    A nonce is the mechanism CSP itself provides for exactly this: the app generates one per
    response, puts it in its own header, and hands it here. Nothing is guessed and nothing is
    weakened — without a nonce the output is byte-for-byte what it was.
    """
    report = _report()

    con_nonce = render_report_html(report, csp_nonce="r4nd0m")
    sin_nonce = render_report_html(report)

    assert '<script type="module" nonce="r4nd0m">' in con_nonce
    assert '<script type="module">' in sin_nonce
    assert "nonce" not in sin_nonce


def test_the_nonce_is_escaped_like_everything_else() -> None:
    """It reaches the HTML from the application, so it is escaped like any other value.

    A nonce is supposed to be random base64, but "supposed to" is not a guarantee about what an
    application hands over, and this file's whole discipline is that nothing reaches the markup
    unescaped.
    """
    salida = render_report_html(_report(), csp_nonce='"><script>x')

    assert '"><script>x' not in salida
