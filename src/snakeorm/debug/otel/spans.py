"""The HYBRID shape of a trace: one root span, one CLIENT child per query, aggregates on both.

Three shapes were compared in Jaeger's own interface, not in JSON, and this one won:

- A single BLOB span is invisible to the search. One operation, nothing to group by, and the whole
  report inside an attribute — the panel of SnakeORM stuffed into Jaeger, paying for Jaeger without
  using it.
- A purely MAPPED tree loses `warnings`, `index_hints` and `summary`: the convention has no
  equivalent for them, so a strict mapping simply drops them.
- The HYBRID keeps both halves. The children make `db.collection.name` and `code.line.number`
  groupable, which is how Trace Statistics re-derives the ORM's own `(sql, origin)` grouping AND
  adds the share of the cost, which the panel does not give. The aggregates ride on the root as
  attributes —searchable ACROSS traces, which is what answers "show me every request with an
  N+1"— and as events, so they get a row on the timeline.

Nothing here executes or sends: it is a pure mapping from a `DebugReport` to spans.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import IntEnum
from time import perf_counter, time_ns
from typing import Protocol

from snakeorm.debug.otel.context import TraceContext
from snakeorm.debug.otel.summary import summarise
from snakeorm.debug.report import DebugReport, RequestInfo
from snakeorm.debug.record import QueryRecord

AttributeValue = str | int | float | bool | tuple[str, ...]
"""What an OTLP attribute can hold. Deliberately narrow: no nesting, no `Any`."""

# --- Semantic conventions, v1.44 ------------------------------------------------------------------
# Written as literals and NOT imported from `opentelemetry.semconv`: the channel has to work with the
# API alone, and with nothing installed at all. `src/test/debug/otel/test_semconv_names.py` checks
# them against the installed package so the literals cannot go stale in silence.
DB_SYSTEM_NAME = "db.system.name"
DB_QUERY_TEXT = "db.query.text"
DB_QUERY_SUMMARY = "db.query.summary"
DB_COLLECTION_NAME = "db.collection.name"
DB_NAMESPACE = "db.namespace"
DB_OPERATION_NAME = "db.operation.name"
DB_RESPONSE_RETURNED_ROWS = "db.response.returned_rows"
DB_QUERY_PARAMETER_PREFIX = "db.query.parameter."
CODE_FILE_PATH = "code.file.path"
CODE_LINE_NUMBER = "code.line.number"
CODE_FUNCTION_NAME = "code.function.name"
HTTP_REQUEST_METHOD = "http.request.method"
HTTP_RESPONSE_STATUS_CODE = "http.response.status_code"
URL_PATH = "url.path"

# --- What the convention has no name for, under our own prefix ------------------------------------
SNAKEORM_QUERY_COUNT = "snakeorm.query_count"
SNAKEORM_DB_MS = "snakeorm.db_ms"
SNAKEORM_WALL_MS = "snakeorm.wall_ms"
# Rides next to `app_ms` because it is the half that was taken OUT of it: `app_ms` is
# `wall - db - mapping`, so a root that omits this one does not add up.
SNAKEORM_MAPPING_MS = "snakeorm.mapping_ms"
SNAKEORM_APP_MS = "snakeorm.app_ms"
SNAKEORM_DUPLICATE_GROUPS = "snakeorm.duplicate_groups"
SNAKEORM_WORST_REPEAT_COUNT = "snakeorm.worst_repeat_count"
SNAKEORM_HAS_N_PLUS_ONE = "snakeorm.has_n_plus_one"
SNAKEORM_SUMMARY = "snakeorm.summary"
SNAKEORM_WARNINGS = "snakeorm.warnings"
SNAKEORM_WARNING = "snakeorm.warning"
SNAKEORM_INDEX_HINTS = "snakeorm.index_hints"
SNAKEORM_INDEX_HINT = "snakeorm.index_hint"
SNAKEORM_COLUMN = "snakeorm.column"
SNAKEORM_WORST_MS = "snakeorm.worst_ms"
SNAKEORM_REPEAT_COUNT = "snakeorm.repeat_count"
SNAKEORM_N = "snakeorm.n"
SNAKEORM_KIND = "snakeorm.kind"

ROOT_SPAN_NAME = "snakeorm"
"""The root's name when there is no request to name it after (a script, a CLI command, a test)."""


class SpanKind(IntEnum):
    """OTLP's span kinds, by their protocol numbers (the payload spells them as integers)."""

    INTERNAL = 1
    SERVER = 2
    CLIENT = 3


@dataclass(frozen=True, slots=True)
class SpanEvent:
    """A point in time inside a span: what gives an aggregate a ROW on Jaeger's timeline."""

    name: str
    time_unix_nano: int
    attributes: tuple[tuple[str, AttributeValue], ...] = ()


@dataclass(frozen=True, slots=True)
class SnakeSpan:
    """One span, already resolved: ids in hex, instants in Unix nanoseconds, attributes flattened.

    `parent_span_id` is an empty string when there is no parent; the payload then OMITS the field,
    because an empty parent and no parent are different things to a collector.
    """

    trace_id: str
    span_id: str
    parent_span_id: str
    name: str
    kind: SpanKind
    start_unix_nano: int
    end_unix_nano: int
    attributes: tuple[tuple[str, AttributeValue], ...]
    events: tuple[SpanEvent, ...] = ()


class IdSource(Protocol):
    """Where the ids come from. A Protocol so a test can assert the tree instead of randomness."""

    def trace_id(self) -> str:
        """A fresh 32-character hex trace id."""
        ...

    def span_id(self) -> str:
        """A fresh 16-character hex span id."""
        ...


class RandomIds:
    """Ids from `os.urandom`, which is what an id needs to be: unique, not meaningful."""

    __slots__ = ()

    def trace_id(self) -> str:
        """16 random bytes in hex, the width OTLP gives a trace."""
        return os.urandom(16).hex()

    def span_id(self) -> str:
        """8 random bytes in hex, the width OTLP gives a span."""
        return os.urandom(8).hex()


def monotonic_epoch_ns() -> int:
    """The Unix nanosecond a `perf_counter()` reading of `0.0` would name.

    `perf_counter` is monotonic and has no origin, so a reading means nothing on its own; anchoring
    it to the wall clock ONCE per export turns every reading into an absolute instant while keeping
    the ORDER and the DISTANCES the monotonic clock measured. That is exactly the trade a timeline
    wants: the wall clock can step (NTP), the differences between queries cannot.
    """
    return time_ns() - int(perf_counter() * 1_000_000_000)


def spans_from_report(
    report: DebugReport,
    *,
    parent: TraceContext | None = None,
    ids: IdSource | None = None,
    epoch_ns: int | None = None,
    parameter_keys: frozenset[str] = frozenset(),
) -> tuple[SnakeSpan, ...]:
    """Map a report to its spans: the root first, then one CLIENT child per statement.

    `parent` is the application's active span, when it has one: the root then hangs off it as an
    INTERNAL section instead of claiming to be the request's server span. `parameter_keys` names
    the parameter positions to send, and is empty by default — the convention makes parameters
    opt-in and there is no way to ask for them in bulk.
    """
    source = RandomIds() if ids is None else ids
    anchor = monotonic_epoch_ns() if epoch_ns is None else epoch_ns
    trace_id = source.trace_id() if parent is None else parent.trace_id
    root_id = source.span_id()

    children = tuple(
        _child_span(
            record,
            trace_id=trace_id,
            parent_span_id=root_id,
            span_id=source.span_id(),
            epoch_ns=anchor,
            parameter_keys=parameter_keys,
        )
        for record in report.records
    )
    root = _root_span(
        report,
        trace_id=trace_id,
        span_id=root_id,
        parent=parent,
        children=children,
        epoch_ns=anchor,
    )
    return (root, *children)


def _child_span(
    record: QueryRecord,
    *,
    trace_id: str,
    parent_span_id: str,
    span_id: str,
    epoch_ns: int,
    parameter_keys: frozenset[str],
) -> SnakeSpan:
    """One statement as a CLIENT span, named after its summary and carrying the `db.*` attributes."""
    summary = summarise(record.sql)
    start = epoch_ns + int(record.started_at * 1_000_000_000)
    attributes: list[tuple[str, AttributeValue]] = [
        (DB_QUERY_TEXT, record.sql),
        (DB_QUERY_SUMMARY, summary.text),
        (DB_OPERATION_NAME, summary.operation),
        (DB_RESPONSE_RETURNED_ROWS, record.rows),
        (SNAKEORM_N, record.n),
        (SNAKEORM_KIND, record.kind.value),
    ]
    if summary.collection:
        attributes.append((DB_COLLECTION_NAME, summary.collection))
    if summary.namespace:
        attributes.append((DB_NAMESPACE, summary.namespace))
    if record.system:
        attributes.append((DB_SYSTEM_NAME, record.system))
    if record.origin is not None:
        attributes.append((CODE_FILE_PATH, record.origin.file))
        attributes.append((CODE_LINE_NUMBER, record.origin.line))
        attributes.append((CODE_FUNCTION_NAME, record.origin.function))
    attributes.extend(_parameters(record, parameter_keys))
    return SnakeSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=summary.text or ROOT_SPAN_NAME,
        kind=SpanKind.CLIENT,
        start_unix_nano=start,
        end_unix_nano=start + int(record.duration_ms * 1_000_000),
        attributes=tuple(attributes),
    )


def _parameters(
    record: QueryRecord, parameter_keys: frozenset[str]
) -> list[tuple[str, AttributeValue]]:
    """The parameters explicitly ASKED for, one key at a time. Empty by default, which is the point.

    The convention collects the PARAMETRISED text by default "because parametrising is a strong
    signal from the user that anything sensitive is in the values", and makes the values themselves
    opt-in. SnakeORM never interpolates, so the text is safe by construction and the values are the
    only thing that could carry user data — which is why they are named one by one and never in
    bulk. The key of a positional parameter is its 0-based index, as the convention says.
    """
    if not parameter_keys:
        return []
    return [
        (f"{DB_QUERY_PARAMETER_PREFIX}{index}", str(value))
        for index, value in enumerate(record.params)
        if str(index) in parameter_keys
    ]


def _root_span(
    report: DebugReport,
    *,
    trace_id: str,
    span_id: str,
    parent: TraceContext | None,
    children: tuple[SnakeSpan, ...],
    epoch_ns: int,
) -> SnakeSpan:
    """The span of the whole unit of work, with the aggregates as attributes AND as events."""
    start, end = _root_window(report, children, epoch_ns)
    duplicates = report.duplicates()
    attributes: list[tuple[str, AttributeValue]] = [
        (SNAKEORM_SUMMARY, report.summary),
        (SNAKEORM_QUERY_COUNT, report.count),
        (SNAKEORM_DB_MS, round(report.total_ms, 3)),
        (SNAKEORM_DUPLICATE_GROUPS, len(duplicates)),
        (SNAKEORM_HAS_N_PLUS_ONE, bool(duplicates)),
        (
            SNAKEORM_WORST_REPEAT_COUNT,
            max((group.count for group in duplicates), default=0),
        ),
    ]
    if report.wall_ms is not None:
        attributes.append((SNAKEORM_WALL_MS, round(report.wall_ms, 3)))
    if report.mapping_ms is not None:
        attributes.append((SNAKEORM_MAPPING_MS, round(report.mapping_ms, 3)))
    if report.app_ms is not None:
        attributes.append((SNAKEORM_APP_MS, round(report.app_ms, 3)))
    if report.warnings:
        attributes.append((SNAKEORM_WARNINGS, report.warnings))
    if report.index_hints:
        attributes.append((SNAKEORM_INDEX_HINTS, _hint_texts(report)))
    attributes.extend(_request_attributes(report.request))
    return SnakeSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id="" if parent is None else parent.span_id,
        name=_root_name(report.request),
        kind=SpanKind.SERVER if parent is None else SpanKind.INTERNAL,
        start_unix_nano=start,
        end_unix_nano=end,
        attributes=tuple(attributes),
        events=_root_events(report, at=end),
    )


def _root_window(
    report: DebugReport, children: tuple[SnakeSpan, ...], epoch_ns: int
) -> tuple[int, int]:
    """The root's start and end, wide enough to CONTAIN every child.

    Two clocks meet here and they must not be allowed to disagree visibly. The request's instant
    (`RequestInfo.at`) comes off the wall clock; the children come off the monotonic one anchored to
    it. In a live process the two are taken microseconds apart and the containment is free — the
    adapters read them on the same line. Widening to the children's extremes costs nothing there and
    guarantees a tree Jaeger can draw when it is not, which is better than a child that renders
    outside its parent.
    """
    starts = [child.start_unix_nano for child in children]
    ends = [child.end_unix_nano for child in children]
    if report.request is None:
        opened = min(starts, default=epoch_ns + int(perf_counter() * 1_000_000_000))
    else:
        opened = int(report.request.at.timestamp() * 1_000_000_000)
    closed = opened + int((report.wall_ms or 0.0) * 1_000_000)
    return min([opened, *starts]), max([closed, *ends])


def _root_name(request: RequestInfo | None) -> str:
    """`GET /orders` when there is a request; the package's name when there is not."""
    if request is None:
        return ROOT_SPAN_NAME
    return f"{request.method} {request.path}".strip()


def _request_attributes(
    request: RequestInfo | None,
) -> list[tuple[str, AttributeValue]]:
    """The HTTP half of the root, under the convention's names. Empty for a standalone report."""
    if request is None:
        return []
    return [
        (HTTP_REQUEST_METHOD, request.method),
        (URL_PATH, request.path),
        (HTTP_RESPONSE_STATUS_CODE, request.status),
    ]


def _hint_texts(report: DebugReport) -> tuple[str, ...]:
    """The advisor's suggestions in the SAME wording the envelope uses: one message, one spelling."""
    return tuple(
        f"{table}.{column} ({ms:.0f}ms)" for table, column, ms in report.index_hints
    )


def _root_events(report: DebugReport, *, at: int) -> tuple[SpanEvent, ...]:
    """Summary, warnings and index hints as events, so each gets a row on the timeline.

    They are stamped at the END of the span because that is when they exist: the duplicates are only
    known once every statement has run.
    """
    events = [
        SpanEvent(
            name=SNAKEORM_SUMMARY,
            time_unix_nano=at,
            attributes=((SNAKEORM_SUMMARY, report.summary),),
        )
    ]
    for group, warning in zip(report.duplicates(), report.warnings, strict=True):
        attributes: list[tuple[str, AttributeValue]] = [
            (SNAKEORM_WARNING, warning),
            (SNAKEORM_REPEAT_COUNT, group.count),
            (DB_QUERY_TEXT, group.sql),
        ]
        if group.origin is not None:
            attributes.append((CODE_FILE_PATH, group.origin.file))
            attributes.append((CODE_LINE_NUMBER, group.origin.line))
        events.append(
            SpanEvent(
                name=SNAKEORM_WARNING, time_unix_nano=at, attributes=tuple(attributes)
            )
        )
    for table, column, worst_ms in report.index_hints:
        events.append(
            SpanEvent(
                name=SNAKEORM_INDEX_HINT,
                time_unix_nano=at,
                attributes=(
                    (DB_COLLECTION_NAME, table),
                    (SNAKEORM_COLUMN, column),
                    (SNAKEORM_WORST_MS, round(worst_ms, 3)),
                ),
            )
        )
    return tuple(events)
