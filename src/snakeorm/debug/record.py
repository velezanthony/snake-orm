"""A `QueryRecord`: the atom of the debug, one captured SQL statement. Immutable (`frozen`): a measurement already taken is not touched."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class QueryKind(StrEnum):
    """Which kind of statement it was, so reads can be told from writes in the panel."""

    SELECT = "select"  # came from fetch_all (SELECT / RETURNING)
    WRITE = "write"  # came from execute (INSERT / UPDATE / DELETE / DDL)


@dataclass(frozen=True, slots=True)
class QueryOrigin:
    """Where the query came from: the USER code frame that fired it (file, line, function).

    It is the "who" that Django Debug Toolbar gives: with the origin you find the code guilty of
    the extra calls (an N+1 or a duplicate), instead of merely seeing that they exist.
    """

    file: str
    line: int
    function: str


@dataclass(frozen=True, slots=True)
class QueryRecord:
    """One captured statement: order, SQL, params, duration, rows and ORIGIN.

    `n` is the (1-based) sequence within the scope, so they can be listed in the ORDER they ran (that is how you read an N+1); `rows` are rows returned (SELECT) or affected (a write); `origin` is the user frame that fired it (or `None` if it could not be resolved).

    `started_at` is a `perf_counter()` reading, monotonic and meaningless on its own: only
    differences between two of them mean anything. It is kept because a duration cannot place a
    query on a TIMELINE — a span needs a start and an end, and synthesising the start makes the
    timeline lie. It costs nothing to keep: the capture driver already reads that clock to measure
    the duration, so this is the first half of a subtraction that was happening anyway.

    `system` is what OpenTelemetry calls the engine (`db.system.name`: `postgresql`, `mysql`,
    `mariadb`, `sqlite`). It is DECLARED by whoever wires the capture driver, never guessed from the
    SQL; empty means undeclared, and the exporter then omits the attribute instead of inventing one.
    """

    n: int
    sql: str
    params: tuple[object, ...]
    duration_ms: float
    rows: int
    kind: QueryKind
    origin: QueryOrigin | None = None
    started_at: float = 0.0
    system: str = ""
