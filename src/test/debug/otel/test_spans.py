"""The HYBRID shape: one root span, one CLIENT child per query, aggregates as attributes AND events.

The three shapes were compared in Jaeger's own interface and this is the one that wins. A single
blob span is invisible to the search (one operation, nothing to group by); a purely mapped tree
loses `warnings`/`index_hints`, which have no equivalent in the convention. The hybrid keeps both:
the children make `db.collection.name` and `code.line.number` groupable —which is how Trace
Statistics re-derives the ORM's own `(sql, origin)` grouping, with the share of the cost— and the
root carries the aggregates as attributes (searchable across traces) and as events (a row on the
timeline).
"""

from __future__ import annotations

from datetime import UTC, datetime

from snakeorm.debug import DebugReport, QueryKind, QueryOrigin, QueryRecord, RequestInfo
from snakeorm.debug.otel import SnakeSpan, SpanKind, TraceContext, spans_from_report


class _Ids:
    """Deterministic ids, so a test can assert the tree instead of the randomness."""

    def __init__(self) -> None:
        self.spans = 0

    def trace_id(self) -> str:
        return "f" * 32

    def span_id(self) -> str:
        self.spans += 1
        return f"{self.spans:016x}"


_ORIGIN = QueryOrigin(file="/app/views.py", line=48, function="order_list")


def _record(n: int, sql: str, *, started_at: float, rows: int = 1) -> QueryRecord:
    """One captured statement of the fake report, with an origin and a declared engine."""
    return QueryRecord(
        n=n,
        sql=sql,
        params=("secret",),
        duration_ms=2.0,
        rows=rows,
        kind=QueryKind.SELECT,
        origin=_ORIGIN,
        started_at=started_at,
        system="postgresql",
    )


def _report() -> DebugReport:
    """A report with an N+1: one list query and two identical detail queries from the same line."""
    records = (
        _record(1, 'SELECT * FROM "orders"', started_at=100.0, rows=2),
        _record(2, 'SELECT * FROM "customers" WHERE "id" = $1', started_at=100.1),
        _record(3, 'SELECT * FROM "customers" WHERE "id" = $1', started_at=100.2),
    )
    report = DebugReport(
        records, wall_ms=50.0, index_hints=(("orders", "customer_id", 18.0),)
    )
    return report.with_request(
        RequestInfo(
            method="GET",
            path="/orders",
            status=200,
            at=datetime(2026, 8, 29, 10, 0, 0, tzinfo=UTC),
        )
    )


def _attributes(span: SnakeSpan) -> dict[str, object]:
    """The span's attributes as a dict, which is how a test wants to read them."""
    return dict(span.attributes)


def test_one_root_span_plus_one_child_per_query() -> None:
    """The shape is 1 + N: the root of the request and a span for each statement."""
    spans = spans_from_report(_report(), ids=_Ids())

    assert len(spans) == 4


def test_every_child_hangs_off_the_root() -> None:
    """The children carry the root's span id as their parent: one tree, not four loose spans."""
    root, *children = spans_from_report(_report(), ids=_Ids())

    assert {child.parent_span_id for child in children} == {root.span_id}


def test_every_span_shares_one_trace() -> None:
    """One request is ONE trace: the root and its children carry the same trace id."""
    spans = spans_from_report(_report(), ids=_Ids())

    assert {span.trace_id for span in spans} == {"f" * 32}


def test_a_child_is_a_client_span() -> None:
    """A query is an outbound call: `CLIENT` is the kind the convention gives a database span."""
    _root, child, *_ = spans_from_report(_report(), ids=_Ids())

    assert child.kind is SpanKind.CLIENT


def test_the_child_is_named_after_the_summary_not_the_sql() -> None:
    """The span name is `db.query.summary`: `SELECT orders`, never the whole statement."""
    _root, child, *_ = spans_from_report(_report(), ids=_Ids())

    assert child.name == "SELECT orders"


def test_the_child_carries_the_current_database_attributes() -> None:
    """The VIGENT names (semconv 1.44): `db.query.text`, `db.system.name`, `db.collection.name`, ..."""
    _root, child, *_ = spans_from_report(_report(), ids=_Ids())
    attributes = _attributes(child)

    assert attributes["db.query.text"] == 'SELECT * FROM "orders"'
    assert attributes["db.system.name"] == "postgresql"
    assert attributes["db.collection.name"] == "orders"
    assert attributes["db.operation.name"] == "SELECT"
    assert attributes["db.query.summary"] == "SELECT orders"
    assert attributes["db.response.returned_rows"] == 2


def test_the_child_carries_the_origin_as_code_attributes() -> None:
    """The origin maps to `code.file.path` / `code.line.number` / `code.function.name`.

    `code.line.number` is what Trace Statistics groups by, and grouping by it is what pulls the
    guilty line out of five hundred spans in two clicks.
    """
    _root, child, *_ = spans_from_report(_report(), ids=_Ids())
    attributes = _attributes(child)

    assert attributes["code.file.path"] == "/app/views.py"
    assert attributes["code.line.number"] == 48
    assert attributes["code.function.name"] == "order_list"


def test_the_params_never_travel() -> None:
    """No parameter reaches the backend by default: the convention makes them opt-in, key by key.

    The text that DOES travel is parametrised, which is the whole reason the convention collects it:
    SnakeORM never interpolates a value into SQL, so `db.query.text` cannot carry user data.
    """
    spans = spans_from_report(_report(), ids=_Ids())
    serialised = repr([span.attributes for span in spans])

    assert "secret" not in serialised


def test_a_named_parameter_can_be_opted_in_one_key_at_a_time() -> None:
    """Asking for parameter `0` sends that one and only that one, as `db.query.parameter.0`."""
    _root, child, *_ = spans_from_report(
        _report(), ids=_Ids(), parameter_keys=frozenset({"0"})
    )

    assert _attributes(child)["db.query.parameter.0"] == "secret"


def test_an_undeclared_engine_omits_the_attribute() -> None:
    """With no declared engine, `db.system.name` is absent — never an empty string or a guess."""
    record = QueryRecord(
        n=1,
        sql="SELECT 1",
        params=(),
        duration_ms=1.0,
        rows=1,
        kind=QueryKind.SELECT,
        started_at=1.0,
    )
    _root, child = spans_from_report(DebugReport((record,)), ids=_Ids())

    assert "db.system.name" not in _attributes(child)


def test_the_root_flags_the_n_plus_one_for_searching() -> None:
    """`snakeorm.has_n_plus_one` on the root is what answers "show me every request with an N+1"."""
    root, *_ = spans_from_report(_report(), ids=_Ids())

    assert _attributes(root)["snakeorm.has_n_plus_one"] is True


def test_a_clean_report_says_so_instead_of_omitting_the_flag() -> None:
    """The flag is FALSE on a clean request, not missing: an absent attribute is not searchable."""
    record = QueryRecord(
        n=1,
        sql='SELECT * FROM "orders"',
        params=(),
        duration_ms=1.0,
        rows=1,
        kind=QueryKind.SELECT,
        started_at=1.0,
    )
    root, _child = spans_from_report(DebugReport((record,)), ids=_Ids())

    assert _attributes(root)["snakeorm.has_n_plus_one"] is False


def test_the_root_carries_the_aggregates_as_attributes() -> None:
    """The counts and the timings ride on the root, which is what makes them comparable BETWEEN traces."""
    root, *_ = spans_from_report(_report(), ids=_Ids())
    attributes = _attributes(root)

    assert attributes["snakeorm.query_count"] == 3
    assert attributes["snakeorm.duplicate_groups"] == 1
    assert attributes["snakeorm.wall_ms"] == 50.0
    assert attributes["snakeorm.summary"] == _report().summary


def test_the_root_timings_add_up_to_the_wall_clock() -> None:
    """`app_ms` is `wall - db - mapping`, so a root that omits the mapping does not add up.

    Somebody reading the trace subtracts: if `db_ms + app_ms` falls short of `wall_ms` and nothing
    on the span says where the rest went, the numbers look wrong rather than incomplete.
    """
    report = DebugReport(_report().records, wall_ms=50.0, mapping_ms=6.0)
    attributes = _attributes(spans_from_report(report, ids=_Ids())[0])

    def ms(name: str) -> float:
        value = attributes[name]
        assert isinstance(value, float)
        return value

    assert ms("snakeorm.mapping_ms") == 6.0
    assert ms("snakeorm.db_ms") + ms("snakeorm.mapping_ms") + ms(
        "snakeorm.app_ms"
    ) == ms("snakeorm.wall_ms")


def test_a_root_with_no_mapping_measured_omits_the_attribute() -> None:
    """No mapping measured is not zero mapping: the attribute is absent, never a zero."""
    root, *_ = spans_from_report(_report(), ids=_Ids())

    assert "snakeorm.mapping_ms" not in _attributes(root)


def test_the_warnings_ride_as_attributes_and_as_events() -> None:
    """`warnings` has no equivalent in the convention: it goes as a `snakeorm.*` array AND as events.

    The array is what a search filters on; the event is what gets a ROW on the timeline, which is
    where somebody reading a trace actually looks.
    """
    root, *_ = spans_from_report(_report(), ids=_Ids())

    assert _attributes(root)["snakeorm.warnings"] == tuple(_report().warnings)
    assert [event.name for event in root.events].count("snakeorm.warning") == 1


def test_the_index_hints_ride_as_attributes_and_as_events() -> None:
    """Same treatment for the advisor's suggestions: searchable on the root, visible on the timeline."""
    root, *_ = spans_from_report(_report(), ids=_Ids())

    assert _attributes(root)["snakeorm.index_hints"] == ("orders.customer_id (18ms)",)
    assert [event.name for event in root.events].count("snakeorm.index_hint") == 1


def test_the_root_is_named_after_the_request() -> None:
    """With a request, the root reads `GET /orders`; the HTTP attributes travel with it."""
    root, *_ = spans_from_report(_report(), ids=_Ids())
    attributes = _attributes(root)

    assert root.name == "GET /orders"
    assert attributes["http.request.method"] == "GET"
    assert attributes["url.path"] == "/orders"
    assert attributes["http.response.status_code"] == 200


def test_an_orphan_root_is_a_server_span() -> None:
    """With no active context, our root IS the server span of the request: nothing above it."""
    root, *_ = spans_from_report(_report(), ids=_Ids())

    assert (root.kind, root.parent_span_id) == (SpanKind.SERVER, "")


def test_an_adopted_root_hangs_off_the_application_span() -> None:
    """With an active context, the root becomes INTERNAL and hangs off the app's span.

    Two SERVER spans for one request would be a lie about the topology: the application's is the
    server span, ours is a section inside it.
    """
    parent = TraceContext(trace_id="a" * 32, span_id="b" * 16)
    root, *children = spans_from_report(_report(), ids=_Ids(), parent=parent)

    assert (root.kind, root.parent_span_id, root.trace_id) == (
        SpanKind.INTERNAL,
        "b" * 16,
        "a" * 32,
    )
    assert {child.trace_id for child in children} == {"a" * 32}


def test_the_timeline_is_measured_not_invented() -> None:
    """Each child starts at its own `started_at` and lasts its own duration, in nanoseconds.

    This is what `started_at` exists for. With only a duration, the second and third spans would
    have to be piled onto a synthesised start and the timeline would show a shape that never
    happened.
    """
    _root, first, second, third = spans_from_report(_report(), ids=_Ids())

    assert second.start_unix_nano - first.start_unix_nano == 100_000_000
    assert third.start_unix_nano - second.start_unix_nano == 100_000_000
    assert first.end_unix_nano - first.start_unix_nano == 2_000_000


def test_the_children_live_inside_the_root() -> None:
    """No child starts before the root or ends after it: a tree Jaeger can draw."""
    root, *children = spans_from_report(_report(), ids=_Ids())

    assert all(root.start_unix_nano <= child.start_unix_nano for child in children)
    assert all(child.end_unix_nano <= root.end_unix_nano for child in children)


def test_a_report_with_no_records_still_gives_a_root() -> None:
    """A request that ran no SQL is still a trace: the root alone, with a count of zero."""
    spans = spans_from_report(DebugReport(()), ids=_Ids())

    assert len(spans) == 1
    assert _attributes(spans[0])["snakeorm.query_count"] == 0


def test_a_schema_qualified_query_names_the_table_not_the_schema() -> None:
    """A qualified table gives `db.collection.name` the TABLE and `db.namespace` the schema.

    SnakeORM emits every Postgres table as `"public"."users"`, so this is not an edge case: it is
    the normal shape of the SQL a real request produces.
    """
    record = QueryRecord(
        n=1,
        sql='SELECT "id" FROM "public"."users" WHERE "id" = %s',
        params=(),
        duration_ms=1.0,
        rows=1,
        kind=QueryKind.SELECT,
        started_at=1.0,
    )
    _root, child = spans_from_report(DebugReport((record,)), ids=_Ids())
    attributes = _attributes(child)

    assert child.name == "SELECT users"
    assert attributes["db.collection.name"] == "users"
    assert attributes["db.namespace"] == "public"


def test_an_unqualified_query_omits_the_namespace() -> None:
    """With no schema in the SQL the attribute is absent, not an empty string."""
    _root, child, *_ = spans_from_report(_report(), ids=_Ids())

    assert "db.namespace" not in _attributes(child)
