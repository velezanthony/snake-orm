"""HTML renderer of the debug panel: a pure `DebugReport -> str` function, reused by the SSR and the sidecar.

The panel is a DRAGGABLE floating button (a FAB) that opens a WIDE offcanvas (nearly the whole page)
so the queries can be read with room to breathe. The priority is READING the SQL: each query comes
expanded, with the keywords highlighted and with the PLACEHOLDERS already substituted by their real
value (only to DISPLAY; execution stays parameterised). Collapsing (one or all) and paging are
secondary tools.

The CSS and the JS live in their own files (`assets/css/`, `assets/js/`) and get INLINED here at
render time: the panel is injected into somebody else's pages and cannot depend on external assets.
The JS is isolated with Shadow DOM, so the host's CSS never touches it (see `assets/js/panel.js`).

A non-negotiable rule: EVERYTHING from the report (SQL, params) goes through `html.escape`; without
that, a `<script>` in a param would be an XSS. The keyword highlighting and the param substitution
operate on text that is then escaped whole.
"""

from __future__ import annotations

import os
import re
from html import escape
from importlib import resources

from snakeorm.debug.channel import SnakeDebugChannel
from snakeorm.debug.config import SnakeDebugLanguage
from snakeorm.debug.record import QueryOrigin
from snakeorm.debug.report import DebugReport

# The `snake-debug-panel` marker is the injection CONTRACT: the tests (deliver/wsgi/asgi/django)
# check that it shows up before `</body>`. It is kept as a class on the root container (light DOM).
_ROOT_MARKER = "snake-debug-panel"

# How many queries per page in the offcanvas (the pager only shows up if that is exceeded).
_PAGE_SIZE = 25

# Assets organised by responsibility: `css/`, `js/`, `img/`, `pages/`. They are read ONCE and
# inlined (the panel is injected into somebody else's pages and cannot depend on external requests:
# the CSP blocks them).
_ASSETS = resources.files("snakeorm.debug") / "assets"


def _asset(*parts: str) -> str:
    """Read an asset from the by-responsibility tree (e.g. `_asset("css", "panel.css")`)."""
    node = _ASSETS
    for part in parts:
        node = node / part
    return node.read_text(encoding="utf-8")


# CSS assembled by responsibility: the app shell + the panel components.
_PANEL_CSS = _asset("css", "snake_orm_app.css") + "\n" + _asset("css", "panel.css")

# JS: the modules CONCATENATED in dependency order (language → panel → history → snake_orm_app).
# There is no runtime `import` (the inlining would not resolve it and the CSP would block it): they
# share scope by living in the SAME `<script type="module">`, so the ORDER *is* the dependency
# mechanism — `history.js` reads `SnakeOrmPanel.safe`, and a `const` used before its declaration
# takes the whole bundle down inside somebody else's page. The editor stitches them together with
# the `/// <reference>` directives.
_PANEL_JS = "\n".join(
    _asset("js", name)
    for name in ("language.js", "panel.js", "history.js", "snake_orm_app.js")
)

# STATIC content of the informational views (plain HTML with `data-t`; each one is one more view).
_HELP_HTML = _asset("pages", "help.html")
_CLI_HTML = _asset("pages", "cli.html")
_CONFIG_HTML = _asset("pages", "config.html")
_DBFIRST_HTML = _asset("pages", "database_first.html")
_HISTORY_HTML = _asset("pages", "history.html")

# The views of the menu besides "Consultas": (view name, i18n key, HTML, ES label). The JS switches
# by `data-view`; `render_report_html` generates the button + panel of each in a loop.
#
# The first four are STATIC. `history` is the odd one: the server paints an empty skeleton and the
# client fills `.snk-history-list` at runtime with the calls the page makes after the render.
_INFO_VIEWS: tuple[tuple[str, str, str, str], ...] = (
    ("history", "menu_history", _HISTORY_HTML, "Historial"),
    ("help", "menu_help", _HELP_HTML, "Ayuda"),
    ("config", "menu_config", _CONFIG_HTML, "Config"),
    ("cli", "menu_cli", _CLI_HTML, "CLI"),
    ("dbfirst", "menu_dbfirst", _DBFIRST_HTML, "DB-first"),
)

_HISTORY_VIEW = "history"

# What the FAB badge COUNTS, said out loud. It starts as this request's queries and the history tab
# grows it with every call the page makes afterwards, so from the second call on it stops matching
# the report printed right underneath it. A number that disagrees with the one beside it has to be
# able to say why it does.
_BADGE_TIP = (
    "Consultas desde que cargó la página: las de esta petición más las de las llamadas "
    "posteriores, que verás en Historial."
)

# SQL keywords to highlight so the query reads at a glance (the ORM emits them in uppercase).
_SQL_KEYWORDS = (
    "SELECT",
    "FROM",
    "WHERE",
    "LEFT",
    "RIGHT",
    "INNER",
    "OUTER",
    "FULL",
    "CROSS",
    "JOIN",
    "ON",
    "AND",
    "OR",
    "NOT",
    "IN",
    "IS",
    "NULL",
    "AS",
    "ORDER",
    "GROUP",
    "BY",
    "HAVING",
    "LIMIT",
    "OFFSET",
    "INSERT",
    "INTO",
    "VALUES",
    "UPDATE",
    "SET",
    "DELETE",
    "RETURNING",
    "DISTINCT",
    "UNION",
    "EXCEPT",
    "INTERSECT",
    "ALL",
    "EXISTS",
    "BETWEEN",
    "LIKE",
    "ILIKE",
    "ASC",
    "DESC",
    "CASE",
    "WHEN",
    "THEN",
    "ELSE",
    "END",
    "COALESCE",
    "CAST",
    "WITH",
    "USING",
)
_KW_RE = re.compile(r"\b(" + "|".join(_SQL_KEYWORDS) + r")\b", re.IGNORECASE)

# Positional placeholders we substitute by their value to DISPLAY: `?` (sqlite), `%s` (psycopg2),
# `$N` (numbered). The `$N` carries its index; `?`/`%s` are consumed in order.
_PLACEHOLDER_RE = re.compile(r"\$(\d+)|\?|%s")

# Icon: the cobra coming out of the database cylinder, composed in `assets/icon.svg` and coloured
# with `currentColor`/CSS (it takes the theme colour). It is read from the file and inlined at
# render time.
_ICON = _asset("img", "icon.svg").strip()


def _short_path(path: str) -> str:
    """Shorten the origin path to DISPLAY: relative to the cwd; if it escapes, `folder/file.py`."""
    try:
        relative = os.path.relpath(path)
    except ValueError:  # paths on different drives (Windows): there is no relative one
        return path
    if not relative.startswith(".."):
        return relative
    return os.path.join(os.path.basename(os.path.dirname(path)), os.path.basename(path))


def _origin_html(origin: QueryOrigin | None) -> str:
    """ORIGIN line of the query: which file/line and function it came from (or empty if unresolved)."""
    if origin is None:
        return ""
    location = f"{_short_path(origin.file)}:{origin.line}"
    return (
        f'<div class="snk-origin">↳ <b>{escape(location)}</b> '
        f'<span><span data-t="origin_in">en</span> {escape(origin.function)}()</span></div>'
    )


def _format_value(value: object) -> str:
    """Represent a param as an SQL literal to DISPLAY (never to execute): NULL, a number or text."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _inline_params(sql: str, params: tuple[object, ...]) -> str:
    """Substitute the positional placeholders by their real value, ONLY to read it (execution stays
    parameterised). Best-effort: if placeholders or params are left over, whatever does not add up
    is left as it is."""
    if not params:
        return sql
    counter = iter(range(len(params)))

    def _replace(match: re.Match[str]) -> str:
        numbered = match.group(1)
        index = int(numbered) - 1 if numbered is not None else next(counter, -1)
        if 0 <= index < len(params):
            return _format_value(params[index])
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_replace, sql)


def _highlight_sql(escaped_sql: str) -> str:
    """Wrap the SQL keywords in `<b class=snk-kw>` for legibility. It operates on ALREADY escaped
    text and inserts only fixed HTML (the user's identifiers/values are never touched)."""
    return _KW_RE.sub(lambda m: f'<b class="snk-kw">{m.group(0)}</b>', escaped_sql)


def _query_html(
    n: int,
    duration_ms: float,
    rows: int,
    kind: str,
    sql: str,
    params: tuple[object, ...],
    origin: QueryOrigin | None,
    *,
    pct: float,
    dup_n: int,
) -> str:
    """One query (expanded by default): a clickable header + a body with the bar, the SQL already
    readable (keywords highlighted, placeholders substituted by their real value) and the ORIGIN
    (file:line)."""
    is_write = kind == "write"
    esc_sql = escape(_inline_params(sql, params))
    dup = f'<span class="snk-dup">×{dup_n}</span>' if dup_n else ""
    return (
        f'<div class="snk-q snk-exp{" snk-w" if is_write else ""}">'
        '<button class="snk-qh" type="button">'
        f'<span class="snk-tag snk-{"write" if is_write else "select"}">{escape(kind)}</span>'
        f'{dup}<span class="snk-qn">#{n}</span>'
        f'<span class="snk-qsql">{esc_sql}</span>'
        f'<span class="snk-ms">{duration_ms:.2f} ms</span>'
        '<span class="snk-caret">▸</span>'
        "</button>"
        '<div class="snk-qbody">'
        f'<div class="snk-bar"><i style="width:{pct:.0f}%"></i></div>'
        f'<p class="snk-sql">{_highlight_sql(esc_sql)}</p>'
        f"{_origin_html(origin)}"
        f'<div class="snk-meta">{rows} <span data-t="rows">filas devueltas/afectadas</span></div>'
        "</div></div>"
    )


def _metric(
    value_html: str, label: str, tip: str, key: str, *, hot: bool = False
) -> str:
    """One metric card of the panel: a big value + a label + a TOOLTIP (`title`) explaining it.

    The native tooltip (`title`) needs no JS and works inside the Shadow DOM; `hot` highlights it in
    amber. `tip` is escaped because it goes in an attribute. `key` is the i18n key: the JS swaps the
    text of the label (`data-t`) and of the tooltip (`data-tt`) when the language changes; the
    server paints the Spanish.
    """
    return (
        f'<div class="snk-m{" snk-hot" if hot else ""}" title="{escape(tip)}" data-tt="{key}_tip">'
        f'<b>{value_html}</b><span data-t="{key}">{escape(label)}</span></div>'
    )


def _view_attrs(name: str, *, envelope: bool | None) -> str:
    """Extra attributes of a view. Only the history has any, and only to say the channel is missing.

    `data-envelope="off"` is emitted ONLY when the channels are known and `envelope` is not among
    them; the CSS swaps the notice in for the list. Unknown channels (a render outside a middleware)
    claim nothing: the notice states a fact.
    """
    if name == _HISTORY_VIEW and envelope is False:
        return ' data-envelope="off"'
    return ""


def _panel_inner(report: DebugReport, *, envelope: bool | None = None) -> str:
    """The panel content (FAB + offcanvas), which goes INSIDE the `<template>` for the shadow root."""
    duplicates = report.duplicates()
    # Keyed by `(sql, origin)` like the groups themselves: the ×N badge of a card counts the
    # repeats OF THAT CALL SITE, not every card that happens to share the SQL.
    dup_counts = {(group.sql, group.origin): group.count for group in duplicates}
    max_ms = max((record.duration_ms for record in report.records), default=0.0)
    slowest = report.slowest()
    n_dups = len(duplicates)

    queries = "".join(
        _query_html(
            record.n,
            record.duration_ms,
            record.rows,
            record.kind.value,
            record.sql,
            record.params,
            record.origin,
            pct=max(3.0, record.duration_ms / max_ms * 100) if max_ms else 3.0,
            dup_n=dup_counts.get((record.sql, record.origin), 0),
        )
        for record in report.records
    )
    # Warnings built out of translatable spans (the JS swaps `warn_pre`/`warn_post`); the number and
    # the SQL go outside the spans. "N+1" stays in the default text (a contract of the panel).
    warnings = ""
    if n_dups:
        items = "".join(
            f'<li><span data-t="warn_pre">La misma SQL corrió</span> {group.count} '
            f'<span data-t="warn_post">veces (posible N+1):</span> {escape(group.sql)}</li>'
            for group in duplicates
        )
        # Collapsible (`<details>`, no JS): CLOSED by default so it does not eat the queries' room.
        # The summary is one line with the counter; on opening, the list is capped and scrolls on its
        # own.
        warnings = (
            '<details class="snk-warns">'
            '<summary class="snk-warns-sum">'
            f'<span class="snk-warns-badge">{n_dups}</span>'
            '<span data-t="warns_title">posibles N+1</span></summary>'
            f'<ul class="snk-warns-list">{items}</ul></details>'
        )

    # Metrics: always queries/DB/duplicates/slowest; plus "petición" (the wall) when the middleware
    # measured it, "mapeo" when the collector measured it, and "en app" = the rest. Those three
    # ADD UP to the request, which is the whole point: they tell a slow DB from a slow ORM from
    # slow application code.
    cards = [
        _metric(
            str(report.count),
            "queries",
            "Nº de sentencias SQL que corrió esta petición.",
            "queries",
        )
    ]
    if report.wall_ms is not None:
        cards.append(
            _metric(
                f"{report.wall_ms:.1f}<small>ms</small>",
                "petición",
                "Tiempo total del request en el servidor, de principio a fin. No incluye el viaje "
                "de red hasta tu navegador.",
                "req",
            )
        )
    cards.append(
        _metric(
            f"{report.total_ms:.1f}<small>ms</small>",
            "en BD",
            "Lo que la app esperó al driver, no lo que el motor tardó en ejecutar: incluye el "
            "viaje de red a la BD.",
            "db",
        )
    )
    if report.mapping_ms is not None:
        cards.append(
            _metric(
                f"{report.mapping_ms:.1f}<small>ms</small>",
                "mapeo",
                "Convertir filas en objetos: el coste del ORM. Tu código no está aquí dentro.",
                "map",
            )
        )
    if report.app_ms is not None:
        cards.append(
            _metric(
                f"{report.app_ms:.1f}<small>ms</small>",
                "en app",
                "El resto = petición − BD − mapeo: tu Python y la plantilla.",
                "app",
            )
        )
    cards.append(
        _metric(
            str(n_dups),
            "duplicadas",
            "Misma SQL y misma línea corriendo más de una vez (posible N+1 o trabajo repetido).",
            "dups",
            hot=bool(n_dups),
        )
    )
    slowest_ms = slowest.duration_ms if slowest else 0.0
    cards.append(
        _metric(
            f"{slowest_ms:.2f}<small>ms</small>",
            "más lenta",
            "Duración de la query más lenta de esta petición.",
            "slowest",
        )
    )
    metrics = f'<div class="snk-metrics">{"".join(cards)}</div>'
    # Subtitle: "N queries · Xms · N duplicadas". "queries" stays literal (it is the same in EN and
    # so the "N queries" marker does not break); only "duplicadas" is translatable.
    subtitle = (
        f'<div class="snk-sub">{report.count} queries · {report.total_ms:.1f}ms · '
        f'{n_dups} <span data-t="dups">duplicadas</span></div>'
    )
    tools = (
        '<div class="snk-tools">'
        '<button class="snk-btn snk-all" type="button" data-t="collapse">Colapsar todo</button>'
        '<select class="snk-ps" aria-label="Queries per page" data-ta="per_page" data-tt="per_page">'
        f'<option value="25"{" selected" if _PAGE_SIZE == 25 else ""}>25</option>'
        f'<option value="50"{" selected" if _PAGE_SIZE == 50 else ""}>50</option>'
        '<option value="0" data-t="per_page_all">Todas</option>'
        "</select>"
        '<div class="snk-pager">'
        '<button class="snk-pg" data-d="-1" type="button" aria-label="Anterior" data-ta="prev">‹</button>'
        '<span class="snk-pglabel">1 / 1</span>'
        '<button class="snk-pg" data-d="1" type="button" aria-label="Siguiente" data-ta="next">›</button>'
        "</div></div>"
        if report.records
        else ""
    )
    body = (
        queries
        if report.records
        else '<div class="snk-empty" data-t="empty">Sin queries</div>'
    )
    badge_cls = "snk-badge" + (" snk-hot" if n_dups else "")

    # Index suggestions (the advisor): the middleware computes them from the SQL + the metadata and
    # they travel in the report. The box is only painted if this page filtered by an unindexed
    # column.
    hints_html = ""
    if report.index_hints:
        items = "".join(
            f"<li>↳ <b>{escape(f'{table}.{column}')}</b> "
            f'<span class="snk-hint-ms">{ms:.0f} ms</span> '
            f'<span data-t="hint_suf">sin índice; una query lenta filtró aquí</span></li>'
            for table, column, ms in report.index_hints
        )
        # Same collapsible as the warnings: the title is the summary and carries the suggestion count.
        hints_html = (
            '<details class="snk-hints">'
            '<summary class="snk-hints-sum">'
            '<span data-t="hint_title">Índices sugeridos</span>'
            f'<span class="snk-hints-badge">{len(report.index_hints)}</span></summary>'
            f'<ul class="snk-hints-list">{items}</ul></details>'
        )

    # The "Consultas" view (KPIs + queries) + the informational views (Ayuda, Config, CLI, DB-first,
    # all static). The menu on the right (Django Debug Toolbar style) switches between them; the JS
    # toggles the active class by `data-view`. It starts on Consultas.
    queries_view = (
        '<div class="snk-view snk-view-queries snk-active">'
        f"{metrics}{warnings}{hints_html}{tools}"
        f'<div class="snk-list">{body}</div>'
        "</div>"
    )
    info_views = "".join(
        f'<div class="snk-view snk-view-{name}"{_view_attrs(name, envelope=envelope)}>'
        f"{content}</div>"
        for name, _key, content, _label in _INFO_VIEWS
    )
    menu_items = "".join(
        f'<button class="snk-menu-item" type="button" data-view="{name}" '
        f'data-t="{key}">{label}</button>'
        for name, key, _content, label in _INFO_VIEWS
    )
    menu = (
        '<nav class="snk-menu">'
        '<button class="snk-menu-item snk-active" type="button" data-view="queries" '
        'data-t="menu_queries">Consultas</button>'
        f"{menu_items}"
        "</nav>"
    )
    body_row = (
        '<div class="snk-body">'
        f'<div class="snk-views">{queries_view}{info_views}</div>{menu}</div>'
    )

    return (
        f'<button class="snk-fab" type="button" title="SnakeORM · debug" aria-label="SnakeORM debug">'
        f'{_ICON}<span class="{badge_cls}" title="{escape(_BADGE_TIP)}" data-tt="badge_tip">'
        f"{report.count}</span></button>"
        '<div class="snk-back"></div>'
        '<aside class="snk-panel" aria-hidden="true">'
        '<div class="snk-head">'
        f'<div><div class="snk-title">{_ICON}SnakeORM</div>'
        f"{subtitle}</div>"
        '<div class="snk-sp"></div>'
        '<select class="snk-lang" title="Idioma" aria-label="Idioma" '
        'data-tt="lang" data-ta="lang"></select>'
        '<button class="snk-ico snk-theme" type="button" title="Tema" aria-label="Cambiar tema" '
        'data-tt="theme" data-ta="theme_aria">◐</button>'
        '<button class="snk-ico snk-close" type="button" title="Cerrar" aria-label="Cerrar" '
        'data-tt="close" data-ta="close">✕</button>'
        "</div>"
        f"{body_row}"
        "</aside>"
    )


def render_report_html(
    report: DebugReport,
    *,
    standalone: bool = False,
    language: SnakeDebugLanguage = SnakeDebugLanguage.EN,
    csp_nonce: str | None = None,
    token: str | None = None,
    channels: frozenset[SnakeDebugChannel] | None = None,
) -> str:
    """Render the report to a SELF-CONTAINED and ISOLATED HTML fragment (Shadow DOM), all escaped.

    The `#snk-root` container (light DOM, `display:contents` so it takes no room) carries the
    `snake-debug-panel` marker, the `data-lang` (the language it OPENS in, which the JS reads) and a
    `<template>` with the style + markup; the script mounts it into a shadow root where the host's
    CSS does not reach. `standalone=True` (the sidecar) opens the panel and hides the FAB. The text
    is STILL painted in Spanish (the degraded, JS-less path); `data-lang` only fixes which language
    the JS swap starts from.

    `csp_nonce` is what lets the panel survive a strict Content-Security-Policy, and without it the
    failure is SILENT: under `script-src 'self'` — no `unsafe-inline`, no nonce, which is what a
    hardened application ships — the browser blocks the inline `<script type="module">`, the
    template never mounts, and the panel simply is not there. No error on the server, nothing in the
    page. The application generates the nonce per response, puts it in its own header and hands it
    here; with no nonce the output is byte for byte what it was.

    `token` is stamped as `data-token` so the panel knows WHICH request rendered it; with no token
    the attribute is absent rather than empty. `channels` is what the history tab reads to say the
    `envelope` channel is missing; `None` means the caller is not a middleware and knows nothing,
    so nothing is claimed.
    """
    wrap_cls = "snk snk-standalone" if standalone else "snk"
    envelope = None if channels is None else SnakeDebugChannel.ENVELOPE in channels
    inner = _panel_inner(report, envelope=envelope)
    if standalone:
        inner = inner.replace(
            '<aside class="snk-panel"', '<aside class="snk-panel snk-open"', 1
        )
    return (
        f'<div id="snk-root" class="{_ROOT_MARKER}" style="display:contents" '
        f'data-ps="{_PAGE_SIZE}" data-lang="{language.value}"{_token_attr(token)}>'
        "<template>"
        f'<style>{_PANEL_CSS}</style><div class="{wrap_cls}">{inner}</div>'
        "</template>"
        f'<script type="module"{_nonce_attr(csp_nonce)}>{_PANEL_JS}</script>'
        "</div>"
    )


def _token_attr(token: str | None) -> str:
    """` data-token="..."` when there is a token, and nothing at all when there is not.

    Escaped like every other value that reaches this markup: it is minted here today, but the
    parameter is public and the discipline of this file is that nothing gets in unescaped.
    """
    if token is None:
        return ""
    return f' data-token="{escape(token, quote=True)}"'


def _nonce_attr(csp_nonce: str | None) -> str:
    """` nonce="..."` when there is one, and nothing at all when there is not.

    ESCAPED like every other value that reaches this markup. A nonce is supposed to be random
    base64, but "supposed to" is not a guarantee about what an application hands over, and the
    discipline of this file is that nothing gets in unescaped.
    """
    if csp_nonce is None:
        return ""
    return f' nonce="{escape(csp_nonce, quote=True)}"'


def render_report_page(
    report: DebugReport, *, language: SnakeDebugLanguage = SnakeDebugLanguage.EN
) -> str:
    """Wrap the panel in a full HTML document for the sidecar (`/__snake__/{token}`), opened."""
    return (
        f"<!doctype html><html lang={language.value}><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>SnakeORM · debug</title>"
        "<style>body{margin:0;padding:24px 16px;background:#11111b;min-height:100vh}</style></head>"
        f"<body>{render_report_html(report, standalone=True, language=language)}</body></html>"
    )
