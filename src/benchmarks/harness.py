"""Measurement utilities: size configuration, timing, and table formatting.

Every timing uses `time.perf_counter()` (a high-resolution monotonic clock, the right one to
measure durations). Each measurement is kept as an immutable `Measurement` and printed in an
aligned table. `CountingDriver` also lives here, a wrapper that COUNTS the queries issued in order
to prove that the to-many include is NOT N+1.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

from snakeorm.drivers import SnakeDriver


@dataclass(frozen=True)
class BenchConfig:
    """Benchmark sizes, grouped together and easy to turn up or down.

    `compile_iterations` and `emit_iterations` are micro-benchmarks (a cheap operation repeated
    many times for a stable average). `insert_sizes` are the INSERT batches to measure.
    `read_rows` is how many trucks get seeded for the reads. `include_parents` is how many
    makers (parents) are loaded together with their trucks in the to-many include.
    """

    compile_iterations: int
    emit_iterations: int
    insert_sizes: tuple[int, ...]
    read_rows: int
    include_parents: int
    continents: int
    nations: int
    warmup: int


# Default configuration: numbers that give a clear signal on a development machine.
DEFAULT_CONFIG = BenchConfig(
    compile_iterations=1_000,
    emit_iterations=10_000,
    insert_sizes=(1_000, 10_000),
    read_rows=10_000,
    include_parents=200,
    continents=5,
    nations=20,
    warmup=1,
)

# SMALL configuration for the smoke test: it checks that the harness runs, not the timings.
SMALL_CONFIG = BenchConfig(
    compile_iterations=20,
    emit_iterations=100,
    insert_sizes=(50,),
    read_rows=100,
    include_parents=10,
    continents=2,
    nations=4,
    warmup=1,
)


@dataclass(frozen=True)
class Measurement:
    """One measurement: name, number of units, total time, and the label of the unit."""

    name: str
    count: int
    total_seconds: float
    unit: str = "op"

    @property
    def per_unit_ms(self) -> float:
        """Mean time per unit, in milliseconds (0 if there were no units)."""
        return (self.total_seconds / self.count) * 1000 if self.count else 0.0

    @property
    def units_per_sec(self) -> float:
        """Units per second (0 if the total time was zero)."""
        return self.count / self.total_seconds if self.total_seconds else 0.0


def measure_repeated(
    name: str,
    iterations: int,
    action: Callable[[], object],
    *,
    warmup: int,
    unit: str = "op",
) -> Measurement:
    """Time `action` repeated `iterations` times, discarding `warmup` passes beforehand.

    The warm-up throws away the cost of the first pass (lazy imports, first plan, caches), so that
    the measurement reflects the steady state and not the start-up.
    """
    for _ in range(warmup):
        action()
    start = time.perf_counter()
    for _ in range(iterations):
        action()
    total = time.perf_counter() - start
    return Measurement(name=name, count=iterations, total_seconds=total, unit=unit)


def time_call(action: Callable[[], object]) -> float:
    """Time ONE call and return the seconds it took (for batch operations)."""
    start = time.perf_counter()
    action()
    return time.perf_counter() - start


class CountingDriver:
    """Wraps a `SnakeDriver` and COUNTS the `fetch_all`/`execute` calls to prove 'no N+1'.

    It delegates EVERYTHING to the inner driver; it only keeps the count. That way the to-many
    include can show the real number of queries issued (1 root + 1 select-in) against the N+1 a
    naive ORM would issue (one query for the children of every parent).
    """

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields whatever
        `fetch_all` returns. The degradation is written HERE, in plain sight, not by the framework."""
        yield from self.fetch_all(sql, params)

    def __init__(self, inner: SnakeDriver) -> None:
        self._inner = inner
        self.fetch_count = 0
        self.execute_count = 0

    @property
    def query_count(self) -> int:
        """Total queries issued (reads + writes) since the driver was wrapped."""
        return self.fetch_count + self.execute_count

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        """Count the read and delegate to the inner driver."""
        self.fetch_count += 1
        return self._inner.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        """Count the write and delegate to the inner driver."""
        self.execute_count += 1
        return self._inner.execute(sql, params)

    @property
    def last_insert_id(self) -> int:
        """Forward to the inner driver (see the SnakeDriver Protocol)."""
        return self._inner.last_insert_id

    def commit(self) -> None:
        """Delegate the commit."""
        self._inner.commit()

    def rollback(self) -> None:
        """Delegate the rollback."""
        self._inner.rollback()

    def savepoint(self, name: str) -> None:
        """Delegate the savepoint."""
        self._inner.savepoint(name)

    def release_savepoint(self, name: str) -> None:
        """Delegate the savepoint release."""
        self._inner.release_savepoint(name)

    def rollback_to_savepoint(self, name: str) -> None:
        """Delegate the rollback to the savepoint."""
        self._inner.rollback_to_savepoint(name)

    def close(self) -> None:
        """Delegate closing the connection."""
        self._inner.close()


@dataclass
class Section:
    """A group of measurements under a numbered title (one of the 7 benchmark tests)."""

    title: str
    measurements: list[Measurement] = field(default_factory=list)


def format_table(sections: Sequence[Section]) -> str:
    """Format every measurement into an aligned table (one row per measurement, grouped by section).

    Columns: test, units measured, total time (ms), mean time per unit, and rate (units/sec). The
    width of each column is computed so that the table stays readable on a console.
    """
    headers = ("Test", "Count", "Total (ms)", "Mean", "Rate")
    rows: list[tuple[str, str, str, str, str]] = []
    for section in sections:
        for measurement in section.measurements:
            rows.append(
                (
                    measurement.name,
                    f"{measurement.count:,}",
                    f"{measurement.total_seconds * 1000:,.2f}",
                    f"{measurement.per_unit_ms:.4f} ms/{measurement.unit}",
                    f"{measurement.units_per_sec:,.0f} {measurement.unit}/s",
                )
            )
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        if rows
        else len(headers[index])
        for index in range(len(headers))
    ]
    line = "  ".join(
        header.ljust(widths[index]) for index, header in enumerate(headers)
    )
    separator = "  ".join("-" * widths[index] for index in range(len(headers)))
    body = "\n".join(
        "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))
        for row in rows
    )
    return f"{line}\n{separator}\n{body}"
