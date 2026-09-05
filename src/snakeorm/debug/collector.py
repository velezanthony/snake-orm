"""Per-scope collector where the `QueryRecord`s of a unit of work land.

Built on `ContextVar` (neither global nor thread-local): it works in sync and async and does not get contaminated between concurrent requests that share a thread.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from typing import ParamSpec, TypeVar

from snakeorm.debug.origin import capture_origin
from snakeorm.debug.record import QueryKind, QueryRecord
from snakeorm.debug.report import DebugReport

P = ParamSpec("P")
R = TypeVar("R")


class DebugCollector:
    """Accumulate the records of a scope and freeze them into a `DebugReport` on demand.

    It also holds the scope's MAPPING total. It lives here and not on the report because the
    mapping happens INSIDE the scope, exactly like the queries do — the wall clock is the odd one
    out, measured by the middleware around the scope and stamped afterwards.
    """

    __slots__ = ("_mapping_ms", "_records")

    def __init__(self) -> None:
        self._records: list[QueryRecord] = []
        self._mapping_ms = 0.0

    def add(
        self,
        *,
        sql: str,
        params: Sequence[object],
        duration_ms: float,
        rows: int,
        kind: QueryKind,
        started_at: float = 0.0,
        system: str = "",
    ) -> None:
        """Record a statement, numbering it by arrival order (1-based) and noting its ORIGIN.

        The origin (file/line/function of the user code that fired the query) is resolved HERE,
        while the caller's stack is still alive: one frame up is the capture driver and, above
        that, the app's code.

        `started_at` is the monotonic instant the driver measured FROM; `system` the engine it
        declared. Both are passed through untouched: this collector computes neither.
        """
        self._records.append(
            QueryRecord(
                n=len(self._records) + 1,
                sql=sql,
                params=tuple(params),
                duration_ms=duration_ms,
                rows=rows,
                kind=kind,
                origin=capture_origin(),
                started_at=started_at,
                system=system,
            )
        )

    def add_mapping(self, duration_ms: float) -> None:
        """Add a BATCH of hydration to the scope's mapping total (see `timed_mapping`)."""
        self._mapping_ms += duration_ms

    @property
    def mapping_ms(self) -> float:
        """Time spent turning rows into objects in this scope. Zero is MEASURED, not unknown."""
        return self._mapping_ms

    def report(self) -> DebugReport:
        """The snapshot of what has been captured so far."""
        return DebugReport.from_records(self._records, mapping_ms=self._mapping_ms)


# The active collector of the current scope. `None` = nothing is being captured (passthrough).
_active: ContextVar[DebugCollector | None] = ContextVar(
    "snakeorm_debug_collector", default=None
)


@contextmanager
def capture_queries() -> Iterator[DebugCollector]:
    """Open a capture scope and return its collector; on the way out it restores the previous one.

    A synchronous context manager on purpose and still valid for async: setting/restoring a `ContextVar` needs no `await` and the value travels with the task.
    """
    collector = DebugCollector()
    token = _active.set(collector)
    try:
        yield collector
    finally:
        _active.reset(token)


def current_collector() -> DebugCollector | None:
    """The collector of the active scope, or `None` if nothing is being captured."""
    return _active.get()


def timed_mapping(function: Callable[P, R]) -> Callable[P, R]:
    """Mark a callable that turns an ALREADY FETCHED result set into objects, and time it.

    Decorate only a body that has its rows in hand and does nothing but build objects out of them.
    Two things must stay outside or the number lies: I/O of any kind, and resolving a relationship
    that fires its own query. Get that wrong and `DB + MAPPING + APP` stops adding up to the
    request, which is the invariant the panel's cards promise.

    ONE lookup per result set, never per row — the same argument `_hydrate_with_plan` makes about
    the plan. Measured on the hydration loop with the debug OFF: a `ContextVar` read inside the row
    loop costs +52 ns/row (+4.3% on a five-column row), while this gate costs ~130 ns per RESULT
    SET however many rows it holds. A decorator and not a `with` block for the same reason: an
    equivalent `@contextmanager` measured ~1000 ns per result set, which is +80% on the one-row
    read `get()` and `first()` do.

    Do NOT nest two of these: the inner one would be counted twice.

    STREAMING (`iterate`) is deliberately NOT marked: the capture driver's stopwatch around
    `fetch_iter` spans whatever the consumer does BETWEEN rows, so hydration during a stream is
    already inside `db_ms` and timing it again would count it twice. A streaming read reports a
    MAPPING that leaves that share out; the sum stays true.
    """

    @wraps(function)
    def timed(*args: P.args, **kwargs: P.kwargs) -> R:
        collector = current_collector()
        if collector is None:
            return function(*args, **kwargs)
        start = perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            collector.add_mapping((perf_counter() - start) * 1000)

    return timed
