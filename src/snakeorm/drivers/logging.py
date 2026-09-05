"""A driver that LOGS the SQL passing through it, by wrapping another one."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

from snakeorm.drivers.base import SnakeDriver

# Where each line gets written. By default it writes nothing (leave it wired up without making a mess); inject `print`/a logger.
Writer = Callable[[str], None]


def _silent(line: str) -> None:
    """Throws the line away (the default behaviour)."""


def render_params(params: Sequence[object], keys: frozenset[str]) -> str:
    """The named parameters, the rest hidden, and the count always.

    The guide wires these drivers with `write=print`, whose output is the container's stdout and
    from there the log aggregator. So `params=('ana@x.com', '$2b$12$...')` was an email and a
    password hash sitting in a searchable index, with no flag to turn it off.

    Written ONCE for both colours on purpose: the asynchronous driver went on printing raw
    values after the synchronous one stopped, which is the drift this seam keeps suffering.
    """
    if not keys:
        return f"<{len(params)} hidden>"
    shown = [
        repr(value) if str(index) in keys else "<hidden>"
        for index, value in enumerate(params)
    ]
    return f"({', '.join(shown)})"


@contextmanager
def _logged(write: Writer, head: str) -> Iterator[list[str]]:
    """Writes ONE line for the statement, whether it worked or not.

    Every write point used to sit AFTER the inner call, so a statement that raised left no line
    at all: you opened the log at 3:14, found the ten statements before it and a ROLLBACK —that
    one wrote, because `rollback()` follows a call that does not fail— and no trace of what
    caused the rollback. The log showed you everything except the thing you came for.

    And the exception does not carry it either: `drivers/failures.py` builds its message from
    the engine's words, with no SQL and no params in it. The log WAS the only place the failed
    statement existed.

    The caller appends its outcome to the yielded list; if it never gets there, the failure is
    written instead. `except BaseException` and re-raise: a timeout or a cancellation is exactly
    the kind of ending worth having in the log.

    `fetch_iter` does NOT use this, deliberately — see its own docstring.
    """
    outcome: list[str] = []
    try:
        yield outcome
    except BaseException as error:
        write(f"{head} -> FAILED: {type(error).__name__}: {error}")
        raise
    # A boundary counts no rows: `COMMIT` stays `COMMIT`, byte for byte.
    write(f"{head} -> {outcome[0]}" if outcome else head)


class LoggingDriver:
    """Wraps a `SnakeDriver` and logs SQL, params and how much it affected. A pure decorator: it changes nothing.
    It also logs the transaction boundaries (commit/rollback/savepoints); without them the log lies by omission.
    """

    __slots__ = ("_inner", "_parameter_keys", "_write")

    def __init__(
        self,
        inner: SnakeDriver,
        write: Writer = _silent,
        *,
        parameter_keys: frozenset[str] = frozenset(),
    ) -> None:
        """`parameter_keys` names the parameter positions to WRITE OUT, and there is no environment
        variable for it.

        That omission is the decision, and it is the same one `debug/otel/exporter.py` already made
        for the same data: an environment variable is precisely the switch somebody flips in
        production by accident, and this one would put user values into the log aggregator. It takes
        an explicit line of code, key by key — the key of a positional parameter is its 0-based
        index, as the OpenTelemetry convention spells it.

        By default the values are hidden and the COUNT is written instead. The count leaks nothing
        and it is half of what makes a log line readable.
        """
        self._inner = inner
        self._write = write
        self._parameter_keys = parameter_keys

    def _params(self, params: Sequence[object]) -> str:
        """The parameters as this driver writes them. Delegates so both colours render alike."""
        return render_params(params, self._parameter_keys)

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        """Runs the query, logs the SQL and how many rows it returned."""
        with _logged(self._write, f"{sql} -- params={self._params(params)}") as outcome:
            rows = self._inner.fetch_all(sql, params)
            outcome.append(f"{len(rows)} row(s)")
        return rows

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Logs the SQL and yields the rows, counting them WHEN IT IS DONE.

        The counter goes at the end and not at the start on purpose: writing "-> N rows" before
        walking them would require materialising them, which is exactly what this path avoids.
        What actually got consumed is what gets logged, and that is also the interesting figure
        when somebody cuts out with a `break`.
        """
        counter = 0
        try:
            for row in self._inner.fetch_iter(sql, params, chunk=chunk):
                counter += 1
                yield row
        finally:
            self._write(
                f"{sql} -- params={self._params(params)} -> {counter} row(s) streamed"
            )

    def execute(self, sql: str, params: Sequence[object]) -> int:
        """Runs the statement, logs the SQL and how many rows it affected."""
        with _logged(self._write, f"{sql} -- params={self._params(params)}") as outcome:
            affected = self._inner.execute(sql, params)
            outcome.append(f"{affected} row(s)")
        return affected

    @property
    def last_insert_id(self) -> int:
        """The id of the last INSERT (see the Protocol). Forwarded to the wrapped driver."""
        return self._inner.last_insert_id

    def commit(self) -> None:
        """Commits the transaction and writes it down."""
        with _logged(self._write, "COMMIT"):
            self._inner.commit()

    def rollback(self) -> None:
        """Rolls the transaction back and writes it down."""
        with _logged(self._write, "ROLLBACK"):
            self._inner.rollback()

    def savepoint(self, name: str) -> None:
        """Marks a savepoint and writes it down."""
        with _logged(self._write, f"SAVEPOINT {name}"):
            self._inner.savepoint(name)

    def release_savepoint(self, name: str) -> None:
        """Releases a savepoint and writes it down."""
        with _logged(self._write, f"RELEASE SAVEPOINT {name}"):
            self._inner.release_savepoint(name)

    def rollback_to_savepoint(self, name: str) -> None:
        """Rolls back to a savepoint and writes it down."""
        with _logged(self._write, f"ROLLBACK TO SAVEPOINT {name}"):
            self._inner.rollback_to_savepoint(name)

    def close(self) -> None:
        """Closes the INNER driver: the decorator does not keep the connection."""
        with _logged(self._write, "CLOSE"):
            self._inner.close()
