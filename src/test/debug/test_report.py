"""The `DebugReport`: it normalizes the captured `QueryRecord`s and serves them in several formats.

One report, many readers: `to_dict` (JSON envelope / sidecar), `to_text` (curl/terminal),
`to_server_timing` (header). It detects duplicates (the same SQL more than once) and warns about a
possible N+1, which is exactly the signal a debug panel must paint in red. The core is
framework-agnostic: not a single line of web gets in here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from snakeorm.debug import (
    DebugReport,
    QueryKind,
    QueryOrigin,
    QueryRecord,
    RequestInfo,
)


def _rec(
    n: int,
    sql: str,
    *,
    ms: float = 1.0,
    rows: int = 1,
    kind: QueryKind = QueryKind.SELECT,
    params: tuple[object, ...] = (),
    origin: QueryOrigin | None = None,
) -> QueryRecord:
    """Short `QueryRecord` factory for the tests."""
    return QueryRecord(
        n=n,
        sql=sql,
        params=params,
        duration_ms=ms,
        rows=rows,
        kind=kind,
        origin=origin,
    )


def test_count_and_total_ms() -> None:
    """The report adds up how many queries there were and the total time."""
    report = DebugReport.from_records(
        [_rec(1, "SELECT 1", ms=0.5), _rec(2, "SELECT 2", ms=1.5)]
    )
    assert report.count == 2
    assert report.total_ms == 2.0


def test_empty_report() -> None:
    """With no queries: zero, no warnings, and a summary that does not blow up."""
    report = DebugReport.from_records([])
    assert report.count == 0
    assert report.warnings == ()
    assert "0 queries" in report.summary


def test_duplicates_detected() -> None:
    """The same SQL executed more than once is flagged as duplicated (with its count)."""
    report = DebugReport.from_records(
        [
            _rec(1, "SELECT * FROM users"),
            _rec(2, "SELECT * FROM cars WHERE id=%s", params=(1,)),
            _rec(3, "SELECT * FROM cars WHERE id=%s", params=(2,)),
            _rec(4, "SELECT * FROM cars WHERE id=%s", params=(3,)),
        ]
    )
    dups = {group.sql: group.count for group in report.duplicates()}
    assert dups == {"SELECT * FROM cars WHERE id=%s": 3}


def test_warning_on_possible_n_plus_one() -> None:
    """A repeated SQL fires a possible-N+1 warning that names the count."""
    report = DebugReport.from_records(
        [_rec(i, "SELECT * FROM cars WHERE id=%s", params=(i,)) for i in range(1, 6)]
    )
    assert len(report.warnings) == 1
    assert "5" in report.warnings[0]
    assert "N+1" in report.warnings[0]


def test_slowest() -> None:
    """`slowest` returns the record that took the longest."""
    report = DebugReport.from_records(
        [
            _rec(1, "SELECT 1", ms=0.5),
            _rec(2, "SELECT 2", ms=9.0),
            _rec(3, "SELECT 3", ms=1.0),
        ]
    )
    slowest = report.slowest()
    assert slowest is not None
    assert slowest.n == 2


def test_to_dict_shape() -> None:
    """`to_dict` gives an envelope with summary, count, total_ms, warnings and the list of queries."""
    report = DebugReport.from_records(
        [_rec(1, "SELECT id FROM users WHERE id=%s", params=(7,))]
    )
    data = report.to_dict()
    assert data["count"] == 1
    assert data["summary"]
    assert isinstance(data["queries"], list)
    query = data["queries"][0]
    assert query["n"] == 1
    assert query["sql"] == "SELECT id FROM users WHERE id=%s"
    assert query["params"] == [7]


def test_to_dict_params_are_json_safe() -> None:
    """Non-primitive params (any old object) serialize to string: the envelope goes to JSON."""

    class Raro:
        def __str__(self) -> str:
            return "raro!"

    data = DebugReport.from_records([_rec(1, "SELECT %s", params=(Raro(),))]).to_dict()
    queries = data["queries"]
    assert isinstance(queries, list)
    assert queries[0]["params"] == ["raro!"]


def test_to_server_timing_is_w3c() -> None:
    """`to_server_timing` emits the W3C format the browser devtools paint on their own."""
    report = DebugReport.from_records([_rec(1, "SELECT 1", ms=4.0)])
    header = report.to_server_timing()
    assert header.startswith("db;dur=4")
    assert "1 queries" in header


def test_to_text_is_a_table() -> None:
    """`to_text` gives an aligned table readable in a terminal/curl, with one row per query."""
    report = DebugReport.from_records(
        [_rec(1, "SELECT 1", ms=0.5), _rec(2, "SELECT 2", ms=1.5)]
    )
    text = report.to_text()
    assert "SELECT 1" in text
    assert "SELECT 2" in text
    # The summary heads the table.
    assert "2 queries" in text


def test_a_report_has_no_request_identity_by_default() -> None:
    """A standalone report knows nothing about a request: the identity is optional, like `wall_ms`.

    `capture_queries()` is used outside the web too (a script, a test, a CLI command), and there is
    no request to name there. The identity travels the same road `wall_ms` does — absent unless a
    middleware fills it in — instead of forcing four empty strings into every report.
    """
    report = DebugReport.from_records([_rec(1, "SELECT 1")])

    assert report.request is None
    assert report.to_dict()["request"] is None


def test_with_request_names_the_request_that_produced_the_report() -> None:
    """`with_request` copies the report carrying method, path, status and the instant it started."""
    at = datetime(2026, 8, 27, 10, 30, tzinfo=UTC)
    report = DebugReport.from_records([_rec(1, "SELECT 1")]).with_request(
        RequestInfo(method="GET", path="/users/7", status=200, at=at)
    )

    request = report.request
    assert request is not None
    assert (request.method, request.path, request.status) == ("GET", "/users/7", 200)
    assert request.at == at


def test_the_request_identity_travels_in_the_envelope() -> None:
    """`to_dict` carries the identity, with the instant as ISO 8601: N entries stop looking alike.

    A list of reports with no identity is N identical lines. This is what the history section reads
    to say WHICH call each entry was.
    """
    at = datetime(2026, 8, 27, 10, 30, tzinfo=UTC)
    data = (
        DebugReport.from_records([_rec(1, "SELECT 1")])
        .with_request(RequestInfo(method="POST", path="/api/posts", status=201, at=at))
        .to_dict()
    )

    assert data["request"] == {
        "method": "POST",
        "path": "/api/posts",
        "status": 201,
        "at": "2026-08-27T10:30:00+00:00",
    }


def test_the_identity_survives_the_other_copies() -> None:
    """`with_wall_ms` and `with_index_hints` keep the identity: the three describe the same request."""
    report = (
        DebugReport.from_records([_rec(1, "SELECT 1")])
        .with_request(
            RequestInfo(
                method="GET", path="/x", status=200, at=datetime(2026, 1, 1, tzinfo=UTC)
            )
        )
        .with_wall_ms(12.0)
        .with_index_hints((("users", "email", 30.0),))
    )

    assert report.request is not None
    assert report.wall_ms == 12.0
    assert report.index_hints == (("users", "email", 30.0),)


def _at(file: str, line: int, function: str = "view") -> QueryOrigin:
    """A `QueryOrigin` for the tests: the user frame a query came from."""
    return QueryOrigin(file=file, line=line, function=function)


def test_the_same_sql_from_two_places_does_not_collapse_into_one_group() -> None:
    """Two call sites emitting the same SQL are TWO groups: the line is what gets fixed.

    Grouping by SQL alone fused them and threw away the only actionable thing there is. An N+1 is
    fixed on the line that fires it, not on the SQL.
    """
    report = DebugReport.from_records(
        [
            _rec(1, "SELECT * FROM cars WHERE id=%s", origin=_at("/app/a.py", 10)),
            _rec(2, "SELECT * FROM cars WHERE id=%s", origin=_at("/app/a.py", 10)),
            _rec(3, "SELECT * FROM cars WHERE id=%s", origin=_at("/app/b.py", 44)),
            _rec(4, "SELECT * FROM cars WHERE id=%s", origin=_at("/app/b.py", 44)),
        ]
    )

    groups = report.duplicates()

    assert len(groups) == 2
    assert {
        (group.origin.file, group.origin.line) for group in groups if group.origin
    } == {
        ("/app/a.py", 10),
        ("/app/b.py", 44),
    }
    assert all(group.count == 2 for group in groups)


def test_a_duplicate_group_carries_its_timings_and_the_worst_params() -> None:
    """A group carries count, total, average, worst — and the params OF THE WORST run.

    The other runs' params are noise; the slowest one's answer the question you actually have:
    "which value took 18 ms?".
    """
    report = DebugReport.from_records(
        [
            _rec(1, "SELECT %s", ms=2.0, params=(1,), origin=_at("/app/a.py", 10)),
            _rec(2, "SELECT %s", ms=18.0, params=(7,), origin=_at("/app/a.py", 10)),
            _rec(3, "SELECT %s", ms=4.0, params=(3,), origin=_at("/app/a.py", 10)),
        ]
    )

    (group,) = report.duplicates()

    assert group.count == 3
    assert group.total_ms == 24.0
    assert group.average_ms == 8.0
    assert group.worst_ms == 18.0
    assert group.worst_params == (7,)


def test_records_with_no_origin_group_on_their_own() -> None:
    """An unresolved origin is a group key like any other: it groups apart and blows nothing up."""
    report = DebugReport.from_records(
        [
            _rec(1, "SELECT 1"),
            _rec(2, "SELECT 1"),
            _rec(3, "SELECT 1", origin=_at("/app/a.py", 10)),
            _rec(4, "SELECT 1", origin=_at("/app/a.py", 10)),
        ]
    )

    groups = report.duplicates()

    assert len(groups) == 2
    assert sum(1 for group in groups if group.origin is None) == 1


def test_a_query_that_runs_once_per_site_is_not_a_duplicate() -> None:
    """The same SQL fired ONCE from each of two places is repeated work by neither: no group."""
    report = DebugReport.from_records(
        [
            _rec(1, "SELECT 1", origin=_at("/app/a.py", 10)),
            _rec(2, "SELECT 1", origin=_at("/app/b.py", 44)),
        ]
    )

    assert report.duplicates() == ()
    assert report.warnings == ()


def test_the_warning_names_the_line_that_fires_the_n_plus_one() -> None:
    """The N+1 warning names file and line: that is the thing the reader has to go and change."""
    report = DebugReport.from_records(
        [
            _rec(i, "SELECT * FROM cars WHERE id=%s", origin=_at("/app/views.py", 42))
            for i in range(1, 4)
        ]
    )

    (warning,) = report.warnings

    assert "/app/views.py:42" in warning
    assert "N+1" in warning


def test_the_warning_still_works_without_an_origin() -> None:
    """With no resolvable origin the warning drops the location and says the rest."""
    report = DebugReport.from_records([_rec(1, "SELECT 1"), _rec(2, "SELECT 1")])

    (warning,) = report.warnings

    # The WHOLE sentence, because "drops the location" is a claim about what is NOT in it: a
    # containment check passes just as happily on a warning trailing an empty `at`.
    assert warning == "The same SQL ran 2 times (a possible N+1): SELECT 1"


def test_groups_with_the_same_count_keep_the_order_they_ran_in() -> None:
    """A tie in count is broken by ORDER OF ARRIVAL, never by time.

    Ordering a tie by duration would order the list by a MEASUREMENT: the same code reported twice
    would list its warnings differently, and a parity test comparing the two would see drift where
    there is only a stopwatch.
    """
    report = DebugReport.from_records(
        [
            _rec(1, "SELECT a", ms=1.0, origin=_at("/app/a.py", 1)),
            _rec(2, "SELECT b", ms=99.0, origin=_at("/app/b.py", 2)),
            _rec(3, "SELECT a", ms=1.0, origin=_at("/app/a.py", 1)),
            _rec(4, "SELECT b", ms=99.0, origin=_at("/app/b.py", 2)),
        ]
    )

    assert [group.sql for group in report.duplicates()] == ["SELECT a", "SELECT b"]


def test_the_most_repeated_group_is_the_one_listed_first() -> None:
    """The list of duplicates goes from most to least repeated: the worst offender heads it.

    The panel and `warnings` both read this list in order and the reader fixes the first line they
    are shown. Listed the other way round, the loudest N+1 of the request is the last thing said.
    """
    report = DebugReport.from_records(
        [
            _rec(1, "SELECT twice", origin=_at("/app/a.py", 1)),
            _rec(2, "SELECT twice", origin=_at("/app/a.py", 1)),
            *(
                _rec(n, "SELECT four times", origin=_at("/app/b.py", 2))
                for n in range(3, 7)
            ),
            *(
                _rec(n, "SELECT three times", origin=_at("/app/c.py", 3))
                for n in range(7, 10)
            ),
        ]
    )

    assert [group.count for group in report.duplicates()] == [4, 3, 2]
    assert [group.sql for group in report.duplicates()] == [
        "SELECT four times",
        "SELECT three times",
        "SELECT twice",
    ]


def test_a_group_with_no_origin_has_no_location_to_show() -> None:
    """With no resolvable origin the location is EMPTY, so the warning can drop it entirely.

    `warnings` decides whether to name a place by asking whether the location is truthy. Anything
    other than an empty string here is a place, so the reader would be sent to one that does not
    exist.
    """
    report = DebugReport.from_records([_rec(1, "SELECT 1"), _rec(2, "SELECT 1")])

    (group,) = report.duplicates()

    assert group.origin is None
    assert group.location == ""


def test_the_envelope_reports_milliseconds_to_three_decimals() -> None:
    """Every duration in the envelope is rounded to three decimals — not truncated to whole ms.

    They come off `perf_counter`, so untouched they are sixteen digits of noise in a JSON somebody
    reads with their eyes. Three decimals is a microsecond, which is finer than anything the ORM can
    honestly claim to have measured, and it is still a NUMBER of milliseconds: rounding to zero
    decimals would report a half-millisecond query as `0`.
    """
    report = DebugReport.from_records(
        [_rec(1, "SELECT 1", ms=1.23456789)], mapping_ms=2.5555555
    ).with_wall_ms(9.87654321)

    data = report.to_dict()

    assert data["total_ms"] == 1.235
    assert data["db_ms"] == 1.235
    assert data["mapping_ms"] == 2.556
    assert data["wall_ms"] == 9.877
    assert data["app_ms"] == 6.086
    queries = data["queries"]
    assert isinstance(queries, list)
    assert queries[0]["ms"] == 1.235


def test_the_server_timing_header_reports_milliseconds_to_three_decimals() -> None:
    """The header carries the same three decimals: the browser paints the number it is given."""
    report = DebugReport.from_records(
        [_rec(1, "SELECT 1", ms=1.23456789)], mapping_ms=2.5555555
    ).with_wall_ms(9.87654321)

    # Compared part by part and not with `in`: `dur=1.235` is a substring of `dur=1.2345`, so a
    # containment check reads a LONGER number as the one it asked for.
    parts = report.to_server_timing().split(", ")

    assert parts == [
        'db;dur=1.235;desc="1 queries"',
        "map;dur=2.556",
        "app;dur=6.086",
        'total;dur=9.877;desc="request"',
    ]


def test_every_copy_replaces_its_own_field_and_carries_the_rest() -> None:
    """`with_wall_ms`, `with_index_hints` and `with_request` change ONE field each.

    The middleware calls the three in whatever order suits it, so a copy that silently dropped a
    field the previous call had filled in would lose it for good — and the thing lost (the index
    advice, the mapping clock) is exactly what nobody notices is missing.
    """
    request = RequestInfo(
        method="GET", path="/x", status=200, at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    hints = (("users", "email", 30.0),)
    full = (
        DebugReport.from_records([_rec(1, "SELECT 1")], mapping_ms=4.0)
        .with_index_hints(hints)
        .with_wall_ms(12.0)
        .with_request(request)
    )

    for copy in (
        full.with_wall_ms(99.0),
        full.with_index_hints((("cars", "maker_id", 5.0),)),
        full.with_request(request),
    ):
        assert copy.records == full.records
        assert copy.mapping_ms == 4.0
        assert copy.request == request
        assert copy.index_hints != ()
        assert copy.wall_ms is not None


def test_the_envelope_carries_exactly_the_documented_keys() -> None:
    """The envelope's keys are a published contract: `docs/users/guide/debugging` shows them.

    The sidecar and the panel read the dictionary by name, and so does anybody who wired the JSON
    into their own tooling. A renamed key breaks all three at once and raises nothing anywhere.
    """
    data = DebugReport.from_records([_rec(1, "SELECT 1")]).to_dict()

    assert set(data) == {
        "summary",
        "request",
        "count",
        "total_ms",
        "db_ms",
        "mapping_ms",
        "wall_ms",
        "app_ms",
        "warnings",
        "index_hints",
        "queries",
    }
    queries = data["queries"]
    assert isinstance(queries, list)
    assert set(queries[0]) == {"n", "ms", "kind", "sql", "params", "rows", "origin"}


def test_to_text_lines_its_columns_up_under_their_headings() -> None:
    """The text table is ALIGNED: one heading row, a rule under it, and cells that start where the
    heading does.

    That is the whole point of the format — it is read in a terminal, by eye, with `curl`. A cell
    that starts anywhere else turns the table into five columns of prose, and nothing raises.
    """
    headings = ("#", "ms", "rows", "kind", "SQL")
    report = DebugReport.from_records(
        [
            _rec(1, "SELECT 1", ms=0.5, rows=1),
            # `rows` here is ONE digit wide and its heading is four: a column has to be at least as
            # wide as the word on top of it, or the heading spills into the next column.
            _rec(
                222,
                "UPDATE a_table_with_a_long_name SET x = 1",
                ms=12.25,
                rows=9,
                kind=QueryKind.WRITE,
            ),
        ]
    )

    summary, heading, rule, *rows = report.to_text().splitlines()

    assert summary == report.summary
    assert heading.split() == list(headings)
    assert set(rule) == {"-", " "}
    # Where each column begins, read off the rule: one run of dashes per column.
    starts = [
        index
        for index, character in enumerate(rule)
        if character == "-" and (index == 0 or rule[index - 1] == " ")
    ]
    assert len(starts) == len(headings)
    # `startswith` at the offset, not a `split()`: the cell BEGINS in its column. Padded on the
    # right, every value is flush with its heading; padded on the left they drift apart by the
    # length of whatever is in the row.
    assert all(
        heading.startswith(name, start) for name, start in zip(headings, starts)
    ), heading
    for row, cells in (
        (rows[0], ("1", "0.50", "1", "select", "SELECT 1")),
        (rows[1], ("222", "12.25", "9", "write", "UPDATE a_table")),
    ):
        assert all(row.startswith(cell, start) for cell, start in zip(cells, starts)), (
            row
        )
