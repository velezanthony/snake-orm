"""Tests for the report's time breakdown: DB, MAPPING, wall (request) and app (the rest).

The middleware measures the wall clock of the whole request. Out of it come THREE slices that add
up to it: the time waiting on the driver, the time turning rows into objects, and the app's own
Python. Without that wall, only the time in the DB is known. It is what separates "the DB is slow"
from "the ORM is slow" from "my code is slow".
"""

from __future__ import annotations

from snakeorm.debug.html import render_report_html
from snakeorm.debug.record import QueryKind, QueryRecord
from snakeorm.debug.report import DebugReport


def _report(
    *durations_ms: float,
    wall_ms: float | None = None,
    mapping_ms: float | None = None,
) -> DebugReport:
    """A report with one query per given duration, and an optional wall/mapping clock."""
    records = [
        QueryRecord(
            n=i + 1,
            sql="SELECT 1",
            params=(),
            duration_ms=ms,
            rows=1,
            kind=QueryKind.SELECT,
        )
        for i, ms in enumerate(durations_ms)
    ]
    return DebugReport.from_records(records, wall_ms=wall_ms, mapping_ms=mapping_ms)


def test_db_time_is_sum_of_queries() -> None:
    """The time in the DB is the sum of the queries' durations."""
    assert _report(10.0, 30.0).total_ms == 40.0


def test_app_time_is_wall_minus_db_when_mapping_was_not_measured() -> None:
    """With no mapping clock, the app time falls back to wall minus DB (the old formula).

    A report built by hand, or captured outside a session, never mapped anything through the ORM:
    there is no third slice to take out, so the two that exist still add up to the wall.
    """
    report = _report(10.0, 30.0, wall_ms=55.0)
    assert report.wall_ms == 55.0
    assert report.mapping_ms is None
    assert report.app_ms == 15.0  # 55 total - 40 in the DB


def test_app_time_takes_mapping_out_as_well() -> None:
    """With a mapping clock, the app time is wall - DB - MAPPING: the ORM stops hiding inside it."""
    report = _report(10.0, 30.0, wall_ms=55.0, mapping_ms=6.0)
    assert report.mapping_ms == 6.0
    assert report.app_ms == 9.0  # 55 - 40 in the DB - 6 mapping


def test_the_three_slices_add_up_to_the_request() -> None:
    """DB + MAPPING + APP is exactly the request: the panel shows them as a breakdown, so they must.

    This is the invariant the header cards promise the reader. If the mapping stopwatch ever moved
    to a place that also covers I/O, this sum would stop closing and nothing else would say so.
    """
    report = _report(10.0, 30.0, wall_ms=55.0, mapping_ms=6.0)
    assert report.mapping_ms is not None and report.app_ms is not None
    assert report.total_ms + report.mapping_ms + report.app_ms == report.wall_ms


def test_mapping_time_is_none_when_nobody_measured_it() -> None:
    """No mapping clock means UNKNOWN, not zero: an absent measurement is never reported as 0 ms."""
    assert _report(10.0, wall_ms=20.0).mapping_ms is None


def test_app_time_never_negative_with_mapping_either() -> None:
    """If DB + MAPPING 'exceed' the wall (rounding, different clocks), app clamps to 0."""
    assert _report(50.0, wall_ms=55.0, mapping_ms=20.0).app_ms == 0.0


def test_app_time_is_none_without_wall() -> None:
    """With no wall clock measured, the app time is unknown (`None`), not zero."""
    assert _report(10.0).app_ms is None


def test_app_time_never_negative() -> None:
    """If the DB 'exceeds' the wall (different clocks, rounding), app is clamped to 0, not negative."""
    assert _report(100.0, wall_ms=90.0).app_ms == 0.0


def test_with_wall_ms_is_immutable_copy() -> None:
    """`with_wall_ms` returns a COPY with the wall set; the original is not touched."""
    original = _report(10.0)
    stamped = original.with_wall_ms(50.0)
    assert original.wall_ms is None
    assert stamped.wall_ms == 50.0
    assert stamped.app_ms == 40.0


def test_the_copies_carry_the_mapping_clock_along() -> None:
    """`with_wall_ms`/`with_index_hints`/`with_request` keep the mapping already measured.

    The collector measures the mapping INSIDE the scope and the middleware stamps the wall AFTER
    it: a copy that dropped the mapping would silently hand `app_ms` back the old formula.
    """
    stamped = _report(10.0, mapping_ms=4.0).with_wall_ms(50.0).with_index_hints(())
    assert stamped.mapping_ms == 4.0
    assert stamped.app_ms == 36.0  # 50 - 10 in the DB - 4 mapping


def test_envelope_breaks_down_times() -> None:
    """The JSON envelope exposes DB, mapping, wall and app separately."""
    payload = _report(10.0, 30.0, wall_ms=55.0, mapping_ms=6.0).to_dict()
    assert payload["db_ms"] == 40.0
    assert payload["mapping_ms"] == 6.0
    assert payload["wall_ms"] == 55.0
    assert payload["app_ms"] == 9.0


def test_envelope_says_null_when_the_mapping_was_not_measured() -> None:
    """An unmeasured mapping travels as `null`, the same road `wall_ms` takes. Never as 0."""
    assert _report(10.0, wall_ms=20.0).to_dict()["mapping_ms"] is None


def test_server_timing_adds_total_and_app_when_wall_known() -> None:
    """`Server-Timing` carries `total` and `app` besides `db` when the wall was measured."""
    header = _report(10.0, 30.0, wall_ms=55.0).to_server_timing()
    assert "db;dur=40" in header
    assert "app;dur=15" in header
    assert "total;dur=55" in header


def test_server_timing_carries_the_mapping_slice() -> None:
    """`Server-Timing` adds `map` when the mapping was measured, so the header breaks down too.

    It is what a history entry with no body has to read: an HTMX fragment carries headers and
    nothing else.
    """
    header = _report(10.0, 30.0, wall_ms=55.0, mapping_ms=6.0).to_server_timing()
    assert "map;dur=6" in header
    assert "app;dur=9" in header


def test_server_timing_omits_map_when_the_mapping_is_unknown() -> None:
    """With no mapping measured the header does not name it: absent, not zero."""
    assert "map;dur" not in _report(10.0, wall_ms=20.0).to_server_timing()


def test_server_timing_is_db_only_without_wall() -> None:
    """Without a wall, `Server-Timing` reports only `db` (it does not invent a total)."""
    header = _report(10.0).to_server_timing()
    assert "db;dur=10" in header
    assert "total" not in header
    assert "app" not in header


def test_panel_kpis_have_explanatory_tooltips() -> None:
    """Every panel KPI carries a tooltip (`title`) explaining what it measures."""
    html = render_report_html(_report(10.0, 30.0, wall_ms=55.0, mapping_ms=6.0))
    assert 'title="Tiempo total del request' in html  # request
    assert 'title="Lo que la app esperó' in html  # in the DB
    assert 'title="Convertir filas en objetos' in html  # mapping
    assert 'title="El resto' in html  # in the app
    assert 'title="Nº de sentencias SQL' in html  # queries
    assert 'title="Misma SQL y misma línea' in html  # duplicates
    assert 'title="Duración de la query más lenta' in html  # slowest


def test_db_tooltip_says_it_is_waiting_not_engine_time() -> None:
    """The 'en BD' tooltip says it is what the APP WAITED, not what the engine took to execute.

    The engines do not report their execution time in the protocol, so this number is measured with
    a `perf_counter()` around the driver call and carries the round trip. Read as "engine time" it
    makes the reader blame the database for their own network.
    """
    html = render_report_html(_report(10.0, wall_ms=20.0))
    assert "no lo que el motor tardó en ejecutar" in html
    assert "viaje de red a la BD" in html
    assert (
        "no incluye el viaje de red hasta tu navegador" in html.lower()
    )  # 'petición' clarifies it


def test_the_mapping_card_only_shows_when_it_was_measured() -> None:
    """The MAPPING card appears with a mapping clock and is ABSENT without one.

    A card reading `0.0ms` where nothing was measured is the "authoritative and groundless number"
    this panel exists to avoid.
    """
    measured = render_report_html(_report(10.0, wall_ms=20.0, mapping_ms=3.0))
    unmeasured = render_report_html(_report(10.0, wall_ms=20.0))
    # By its TOOLTIP key, which only the header card carries: the history tab paints a `map` label
    # of its own (`hmap_tip`), so the label alone would match a card that is always there.
    assert 'data-tt="map_tip"' in measured
    assert 'data-tt="map_tip"' not in unmeasured
