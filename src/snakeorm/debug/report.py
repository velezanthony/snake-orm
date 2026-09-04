"""The `DebugReport`: it normalises the `QueryRecord`s and serves them in several formats (dict, text, Server-Timing, HTML).

Duplicate detection is the N+1 heuristic: the same SQL repeated FROM THE SAME LINE is the signature
of "one query per parent", and the line is where the fix goes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from snakeorm.debug.record import QueryOrigin, QueryRecord

# Primitives that go to JSON as they are; the rest gets serialised with str() so the envelope does
# not blow up.
_JSON_PRIMITIVES = (int, float, str, bool, type(None))


def _json_safe(value: object) -> object:
    """Let JSON primitives through; convert everything else (datetime, Decimal, UUID...) to `str`.

    The envelope travels inside a JSON response: an unserialisable param would break the whole
    thing.
    """
    if isinstance(value, _JSON_PRIMITIVES):
        return value
    return str(value)


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """The same SQL fired more than once FROM THE SAME PLACE, with its timings.

    The key is `(sql, origin)` and not the SQL alone: the fix goes on the line that fires the
    repeat, so fusing two call sites throws away the only actionable thing there is. `origin` is
    `None` when it could not be resolved, and that is a key like any other.

    `worst_params` are the SLOWEST run's. The rest are noise; these answer "which value took 18 ms?".
    """

    sql: str
    origin: QueryOrigin | None
    count: int
    total_ms: float
    worst_ms: float
    worst_params: tuple[object, ...]

    @property
    def average_ms(self) -> float:
        """Mean time per run of this group."""
        return self.total_ms / self.count

    @property
    def location(self) -> str:
        """`file:line` of the call site, or an empty string when there is no origin."""
        if self.origin is None:
            return ""
        return f"{self.origin.file}:{self.origin.line}"


@dataclass(frozen=True, slots=True)
class RequestInfo:
    """WHICH request produced a report: verb, path, status and the instant it started.

    The four travel together because they are one answer, and one optional field says "no request"
    once instead of four that can disagree. Without it a list of reports is N identical lines.
    """

    method: str
    path: str
    status: int
    at: datetime

    def to_dict(self) -> dict[str, object]:
        """JSON-serialisable form; the instant as ISO 8601 (a `datetime` is not JSON)."""
        return {
            "method": self.method,
            "path": self.path,
            "status": self.status,
            "at": self.at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class DebugReport:
    """The records of a scope, ready to read. Immutable: a snapshot of what ran.

    `wall_ms` is the wall clock of the whole REQUEST (the middleware measures it around the app),
    and it splits into THREE slices that add back up to it: `total_ms` (waiting on the driver),
    `mapping_ms` (turning rows into objects) and `app_ms` (everything else — the user's Python and
    the template). It is `None` when nobody measured it (a standalone report, a sidecar with no
    request): then only the time in the DB is known.
    """

    records: tuple[QueryRecord, ...]
    wall_ms: float | None = None
    # Index suggestions `(table, column, worst_ms)` that the middleware computes with the advisor
    # (only from the SLOW queries): the duration justifies the advice and orders the suggestions.
    index_hints: tuple[tuple[str, str, float], ...] = ()
    # WHICH request this was. Optional for the same reason `wall_ms` is: a standalone capture (a
    # script, a test, a CLI command) has no request to name.
    request: RequestInfo | None = None
    # Time the ORM spent turning rows into objects, measured by the collector INSIDE the scope.
    # `None` (never 0.0) when there was no scope to measure it: absent is not zero.
    mapping_ms: float | None = None

    @classmethod
    def from_records(
        cls,
        records: Iterable[QueryRecord],
        *,
        wall_ms: float | None = None,
        mapping_ms: float | None = None,
    ) -> DebugReport:
        """Freeze a sequence of records into a report (with the optional wall and mapping clocks)."""
        return cls(tuple(records), wall_ms, mapping_ms=mapping_ms)

    def with_wall_ms(self, wall_ms: float) -> DebugReport:
        """Copy the report setting the request wall clock (the middleware measures it at the end)."""
        return DebugReport(
            self.records, wall_ms, self.index_hints, self.request, self.mapping_ms
        )

    def with_index_hints(
        self, hints: tuple[tuple[str, str, float], ...]
    ) -> DebugReport:
        """Copy the report with the index suggestions (the middleware computes them with the advisor)."""
        return DebugReport(
            self.records, self.wall_ms, hints, self.request, self.mapping_ms
        )

    def with_request(self, request: RequestInfo) -> DebugReport:
        """Copy the report naming the request that produced it (the adapters fill it in)."""
        return DebugReport(
            self.records, self.wall_ms, self.index_hints, request, self.mapping_ms
        )

    @property
    def count(self) -> int:
        """How many statements ran."""
        return len(self.records)

    @property
    def total_ms(self) -> float:
        """Total summed time of every statement, in milliseconds (the time IN THE DB)."""
        return sum(record.duration_ms for record in self.records)

    @property
    def app_ms(self) -> float | None:
        """The rest = wall - DB - MAPPING. `None` if the wall was not measured.

        It used to be `wall - DB`, one opaque block where the ORM's own mapping hid among the
        user's Python. With `mapping_ms` measured, that half comes out and this is what is left:
        the application's code and its template. With no mapping measured the old formula stands —
        there is no third slice to take out, and the two that exist still add up to the wall.
        """
        if self.wall_ms is None:
            return None
        mapping = 0.0 if self.mapping_ms is None else self.mapping_ms
        return max(0.0, self.wall_ms - self.total_ms - mapping)

    def duplicates(self) -> tuple[DuplicateGroup, ...]:
        """Groups of `(sql, origin)` that ran MORE than once, from most to least repeated.

        The params are not part of the key: the same SQL with different params is the signature of
        an N+1. The ORIGIN is, because that is the line the reader has to change.
        """
        grouped: dict[tuple[str, QueryOrigin | None], list[QueryRecord]] = {}
        for record in self.records:
            grouped.setdefault((record.sql, record.origin), []).append(record)
        groups = [
            _group(sql, origin, records)
            for (sql, origin), records in grouped.items()
            if len(records) > 1
        ]
        # By count only, and the sort is STABLE: a tie keeps the order the groups first ran in.
        # Breaking the tie on time would order the list by a MEASUREMENT, so the same run reported
        # twice could list its warnings in a different order.
        groups.sort(key=lambda group: group.count, reverse=True)
        return tuple(groups)

    def slowest(self) -> QueryRecord | None:
        """The record that took longest (or `None` if there was none)."""
        if not self.records:
            return None
        return max(self.records, key=lambda record: record.duration_ms)

    @property
    def warnings(self) -> tuple[str, ...]:
        """Readable warnings: today, a possible N+1 per duplicated group, NAMING the call site.

        The location is the actionable half: the SQL says what repeated, the line says where to go.
        It is dropped when the origin could not be resolved, rather than printed empty.
        """
        return tuple(
            f"The same SQL ran {group.count} times (a possible N+1)"
            + (f" at {group.location}" if group.location else "")
            + f": {group.sql}"
            for group in self.duplicates()
        )

    @property
    def summary(self) -> str:
        """One line the dev scans at a glance: how many, how long, and duplicates."""
        return (
            f"{self.count} queries · {self.total_ms:.1f}ms · "
            f"{len(self.duplicates())} duplicates"
        )

    def to_dict(self) -> dict[str, object]:
        """JSON-serialisable envelope (the `snakeorm` block and the sidecar). The params go through `_json_safe` so the JSON does not break."""
        return {
            "summary": self.summary,
            "request": None if self.request is None else self.request.to_dict(),
            "count": self.count,
            "total_ms": round(self.total_ms, 3),
            "db_ms": round(self.total_ms, 3),
            "mapping_ms": None
            if self.mapping_ms is None
            else round(self.mapping_ms, 3),
            "wall_ms": None if self.wall_ms is None else round(self.wall_ms, 3),
            "app_ms": None if self.app_ms is None else round(self.app_ms, 3),
            "warnings": list(self.warnings),
            "index_hints": [
                f"{table}.{column} ({ms:.0f}ms)"
                for table, column, ms in self.index_hints
            ],
            "queries": [
                {
                    "n": record.n,
                    "ms": round(record.duration_ms, 3),
                    "kind": record.kind.value,
                    "sql": record.sql,
                    "params": [_json_safe(param) for param in record.params],
                    "rows": record.rows,
                    "origin": (
                        None
                        if record.origin is None
                        else {
                            "file": record.origin.file,
                            "line": record.origin.line,
                            "function": record.origin.function,
                        }
                    ),
                }
                for record in self.records
            ],
        }

    def to_server_timing(self) -> str:
        """`Server-Timing` header (W3C): the browser devtools paint it by themselves.

        It always carries `db` (the time in the DB) and, when it was measured, `map` (the ORM
        turning rows into objects). If the middleware measured the wall clock, it adds `total` (the
        whole request) and `app` (the rest: the user's Python and the template); that way the
        browser shows the breakdown, and the subtraction against the total response time the
        browser sees IS the network trip.

        `map` goes out even with no wall clock, because it is the ONLY thing a response with no
        body can say about the ORM's own cost: an HTMX fragment carries headers and nothing else."""
        parts = [f'db;dur={round(self.total_ms, 3)};desc="{self.count} queries"']
        if self.mapping_ms is not None:
            parts.append(f"map;dur={round(self.mapping_ms, 3)}")
        if self.wall_ms is not None and self.app_ms is not None:
            parts.append(f"app;dur={round(self.app_ms, 3)}")
            parts.append(f'total;dur={round(self.wall_ms, 3)};desc="request"')
        return ", ".join(parts)

    def to_text(self) -> str:
        """An aligned table, readable in a terminal/curl. The summary heads it; one row per query."""
        header = ("#", "ms", "rows", "kind", "SQL")
        rows = [
            (
                str(record.n),
                f"{record.duration_ms:.2f}",
                str(record.rows),
                record.kind.value,
                record.sql,
            )
            for record in self.records
        ]
        widths = [
            max(len(header[i]), *(len(row[i]) for row in rows))
            if rows
            else len(header[i])
            for i in range(len(header))
        ]
        line = "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(header))
        separator = "  ".join("-" * widths[i] for i in range(len(header)))
        body = "\n".join(
            "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
            for row in rows
        )
        parts = [self.summary, line, separator, body] if rows else [self.summary]
        return "\n".join(parts)


def _group(
    sql: str, origin: QueryOrigin | None, records: list[QueryRecord]
) -> DuplicateGroup:
    """Fold the records of one `(sql, origin)` key into its group (timings + the worst run's params)."""
    worst = max(records, key=lambda record: record.duration_ms)
    return DuplicateGroup(
        sql=sql,
        origin=origin,
        count=len(records),
        total_ms=sum(record.duration_ms for record in records),
        worst_ms=worst.duration_ms,
        worst_params=worst.params,
    )
