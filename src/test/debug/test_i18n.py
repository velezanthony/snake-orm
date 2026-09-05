"""Tests for the panel's i18n contract: the HTML marks the translatable texts and the JS carries both languages.

There is no i18n library: the server paints the Spanish and marks every text with `data-t`/`data-tt`/`data-ta`;
the JS (`panel.js`) holds the ES/EN strings and swaps them, persisting the language in sessionStorage.
"""

from __future__ import annotations

import argparse

import re
from importlib import resources

from snakeorm.debug import SnakeDebugChannel, SnakeDebugLanguage
from snakeorm.debug.html import render_report_html, render_report_page
from snakeorm.debug.record import QueryKind, QueryOrigin, QueryRecord
from snakeorm.debug.report import DebugReport


def _report() -> DebugReport:
    """A report with one query (with origin) and a wall clock, so metrics, body and origin all come out."""
    record = QueryRecord(
        n=1,
        sql="SELECT 1",
        params=(),
        duration_ms=1.0,
        rows=1,
        kind=QueryKind.SELECT,
        origin=QueryOrigin(file="/app/views.py", line=10, function="index"),
    )
    return DebugReport.from_records([record], wall_ms=5.0)


def test_panel_marks_translatable_strings() -> None:
    """The panel marks with `data-t`/`data-tt` the texts and tooltips the JS must be able to swap."""
    html = render_report_html(_report())
    for marker in (
        'data-t="db"',  # the "en BD" label
        'data-tt="db_tip"',  # its tooltip
        'data-t="rows"',  # "filas devueltas/afectadas"
        'data-t="dups"',  # "duplicadas" (in the metrics and the subtitle)
        'data-t="origin_in"',  # the origin's "en"
        "snk-lang",  # language button
    ):
        assert marker in html, marker


def test_panel_default_render_is_spanish() -> None:
    """With no JS, the server paints the Spanish (it works degraded): the labels are in Castilian."""
    html = render_report_html(_report())
    assert ">en BD<" in html
    assert ">duplicadas<" in html


def test_panel_has_menu_with_all_views() -> None:
    """The side menu carries Queries + the History + the four informational views."""
    html = render_report_html(_report())
    assert 'class="snk-menu"' in html
    for view in ("queries", "help", "config", "cli", "dbfirst", "history"):
        assert f'data-view="{view}"' in html, view
        if view != "queries":
            assert f"snk-view-{view}" in html, view
    for key in ("menu_help", "menu_config", "menu_cli", "menu_dbfirst", "menu_history"):
        assert f'data-t="{key}"' in html, key


def test_cli_view_lists_every_command_the_parser_declares() -> None:
    """The CLI view names EVERY subcommand, derived from the parser and not from a list here.

    Three were named by hand and the panel had drifted by three the other way: `scaffold`, `check`
    and `dto` existed and the page did not mention them. A panel that lists nine of twelve reads as
    the complete set — nothing on the page says otherwise — so the reader concludes the tool cannot
    do what it can.

    Derived the same way `test_config_view_lists_every_channel_that_exists` derives from the enum:
    a command added tomorrow fails this the day it appears, rather than the day somebody remembers
    the panel exists. `scaffold` is the one that may live on another page — it has a view of its own
    — so its home is checked across the whole rendered report, which is what the reader browses.
    """
    from snakeorm.cli.app import _build_parser

    subparsers = [
        action
        for action in _build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert subparsers, "the parser stopped declaring subcommands"
    commands = sorted(subparsers[0].choices)
    assert len(commands) >= 10, f"only {len(commands)} subcommands were found"

    html = render_report_html(_report())
    assert "snk-view-cli" in html
    missing = [command for command in commands if f"snakeorm {command}" not in html]

    assert not missing, (
        f"the panel does not mention {missing}. It lists {len(commands) - len(missing)} of "
        f"{len(commands)} commands, and a partial list reads as the complete one."
    )


def test_config_view_documents_the_advisor_threshold() -> None:
    """The Config view documents the advisor threshold (env var and the typed config)."""
    html = render_report_html(_report())
    assert "snk-view-config" in html
    assert "SNAKE_ORM_ADVISE_MS=10" in html
    assert "SnakeDebugConfig(advise_min_ms=25)" in html


def test_config_view_lists_every_channel_that_exists() -> None:
    """The Config view names the FIVE channels of `SnakeDebugChannel`, not a subset."""
    html = render_report_html(_report())
    for channel in SnakeDebugChannel:
        assert f"<code>{channel.value}</code>" in html, channel.value


def test_config_view_declares_the_unimplemented_and_risky_channels() -> None:
    """The Config view says `otel` is declared but not implemented, and that the risky ones drop in production."""
    html = render_report_html(_report())
    for key in ("cfg_ch_otel", "cfg_prod_d"):
        assert f'data-t="{key}"' in html, key
    assert "envelope" in html and "sidecar" in html  # the two RISKY_CHANNELS, named


def test_dbfirst_view_documents_scaffolding() -> None:
    """The DB-first view documents the scaffolding and the mirror model."""
    html = render_report_html(_report())
    assert "snk-view-dbfirst" in html
    assert "snakeorm scaffold create" in html
    assert "@snake_db_first" in html


def test_help_view_no_longer_carries_orm_commands() -> None:
    """The Help no longer carries the ORM commands (they live in the CLI view): it keeps the generic stuff."""
    html = render_report_html(_report())
    assert "snk-view-help" in html
    assert "SNAKE_ORM_DEBUG=ssr,envelope,timing" in html  # turn the panel on
    assert (
        "<code>snakeorm</code>" in html
    )  # the JSON hangs off the `snakeorm` key (envelope channel)
    assert (
        "?_debug=1" not in html
    )  # the query-param trigger no longer exists: the channel is the switch
    assert 'data-t="help_tools"' not in html  # old key withdrawn


def test_language_module_ships_both_languages_and_persistence() -> None:
    """The `js/language.js` module includes the ES and EN strings and the sessionStorage key."""
    js = (
        resources.files("snakeorm.debug") / "assets" / "js" / "language.js"
    ).read_text(encoding="utf-8")
    assert "ES: 'es'" in js and "EN: 'en'" in js  # the LANG enum of valid languages
    assert "'in DB'" in js  # English translation of "en BD"
    assert "'Collapse all'" in js  # English translation of "Colapsar todo"
    assert "snakeorm-debug-lang" in js  # the language's sessionStorage key


def test_panel_default_open_language_is_english() -> None:
    """By default, the panel starts up in English: the `#snk-root` carries `data-lang="en"` for the JS."""
    assert 'data-lang="en"' in render_report_html(_report())


def test_panel_open_language_follows_the_config() -> None:
    """With `language=ES`, the panel's `data-lang` switches to Spanish (the JS opens in that language)."""
    assert 'data-lang="es"' in render_report_html(
        _report(), language=SnakeDebugLanguage.ES
    )


def test_sidecar_page_sets_html_lang_and_data_lang() -> None:
    """The sidecar page sets `<html lang>` and the panel's `data-lang` to the configured language."""
    en = render_report_page(_report())
    assert "<html lang=en>" in en and 'data-lang="en"' in en
    es = render_report_page(_report(), language=SnakeDebugLanguage.ES)
    assert "<html lang=es>" in es and 'data-lang="es"' in es


def test_js_opens_in_the_server_provided_language() -> None:
    """The panel's JS starts up in the language the server paints (`data-lang`), not in a fixed default."""
    js = (
        resources.files("snakeorm.debug") / "assets" / "js" / "snake_orm_app.js"
    ).read_text(encoding="utf-8")
    assert (
        "dataset.lang" in js
    )  # the startup reads the server default off the #snk-root


def test_the_panel_carries_its_own_token() -> None:
    """The `#snk-root` stamps the request's sidecar token, so the page can name itself.

    Without it the client has no way to refer to the request that rendered the page it is running
    in, which is the anchor the history entries hang off.
    """
    html = render_report_html(_report(), token="abc123")

    assert 'data-token="abc123"' in html


def test_without_a_token_the_panel_stamps_none() -> None:
    """No token means no attribute: the panel does not invent an identity it was not given."""
    assert "data-token" not in render_report_html(_report())


def test_the_history_is_a_tab_with_an_empty_state() -> None:
    """The history is a fifth view, with the container the client paints into and an empty state.

    It is a TAB and not a strip inside the report: the report view describes the render, and these
    are the calls that came after it.
    """
    html = render_report_html(_report())

    assert 'data-view="history"' in html
    assert 'data-t="menu_history"' in html
    assert "snk-view-history" in html
    assert 'class="snk-history-list"' in html  # where the client appends its entries
    assert 'data-t="hist_empty"' in html


_HISTORY_OFF = '<div class="snk-view snk-view-history" data-envelope="off">'
"""The history view MARKED as envelope-less. The whole element, because the CSS that reads the
attribute is inlined into the same document and a bare substring would match the stylesheet."""


def test_the_history_says_so_when_the_envelope_channel_is_off() -> None:
    """With the channels known and `envelope` missing, the tab SAYS the history cannot work.

    The history reads the report the ORM hangs off JSON responses, so without that channel there is
    nothing to stack. The panel says it where the user goes looking; it does not switch the channel
    on behind their back — `ssr` and `envelope` are independent.
    """
    off = render_report_html(_report(), channels=frozenset({SnakeDebugChannel.SSR}))

    assert _HISTORY_OFF in off
    assert 'data-t="hist_off"' in off


def test_the_history_makes_no_claim_when_the_channels_are_unknown() -> None:
    """Rendered outside a middleware there are no channels to read, so nothing is claimed."""
    unknown = render_report_html(_report())
    on = render_report_html(
        _report(),
        channels=frozenset({SnakeDebugChannel.SSR, SnakeDebugChannel.ENVELOPE}),
    )

    assert _HISTORY_OFF not in unknown
    assert _HISTORY_OFF not in on


def test_the_history_tab_leaves_the_report_view_alone() -> None:
    """The queries view is byte for byte what it was: the history lives in its own view.

    The panel gains a menu entry and nothing else. A debug tool that redraws the report to make
    room for a new feature has broken the thing the reader came for.
    """
    html = render_report_html(_report())
    start = html.index('<div class="snk-view snk-view-queries')
    end = html.index('<div class="snk-view snk-view-', start + 1)

    assert "snk-history" not in html[start:end]


_KEY = re.compile(r'data-t{0,2}[ta]?="([a-z0-9_]+)"')


def _language_blocks() -> tuple[str, str]:
    """The ES half and the EN half of `language.js`, split at the `[LANG.EN]` entry."""
    js = (
        resources.files("snakeorm.debug") / "assets" / "js" / "language.js"
    ).read_text(encoding="utf-8")
    spanish, marker, english = js.partition("[LANG.EN]: {")
    assert marker, "the EN block of language.js was not found"
    return spanish, english


def test_every_rendered_key_is_translated_in_both_languages() -> None:
    """Every `data-t`/`data-tt`/`data-ta` key the panel paints has an ES entry AND an EN entry.

    It checks an EXISTENCE, which is mechanical, and not that a translation is good, which no test
    can measure. A key present in one half and not the other leaves the panel half-swapped for the
    reader of one language, and nothing else would notice.
    """
    html = render_report_html(_report(), channels=frozenset({SnakeDebugChannel.SSR}))
    spanish, english = _language_blocks()

    keys = set(_KEY.findall(html))
    assert len(keys) >= 40, (
        f"only {len(keys)} keys were found: the parser stopped working"
    )

    missing = sorted(
        key for key in keys if f"{key}:" not in spanish or f"{key}:" not in english
    )
    assert missing == [], f"keys with no entry in both languages: {missing}"
