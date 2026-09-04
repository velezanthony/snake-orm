"""Driver decorators: logging, pooling and timeouts WITHOUT touching the core.

The seam was well designed from the start: `SnakeDriver` is a `Protocol` and both `SnakeSession`
and `MigrationRunner` receive it INJECTED. So the entire production layer is solved by wrapping,
not by modifying. Neither the compiler, nor the dialect, nor the AST ever find out.

And that is exactly the test that matters: a decorated driver has to still be a driver.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.drivers import LoggingDriver, SnakeDriver


class _FakeDriver:
    """Pretend driver that notes down what it is asked for, to observe the decorator."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []
        self.closed = False
        self.rows: list[tuple[object, ...]] = [(1, "Ana")]

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.calls.append(("fetch_all", sql, tuple(params)))
        return self.rows

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """Test double: there is no engine behind it to stream from, so it yields what `fetch_all`
        returns. The degradation is written HERE, in plain sight, not done by the framework."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.calls.append(("execute", sql, tuple(params)))
        return 3

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:
        self.calls.append(("commit", "", ()))

    def rollback(self) -> None:
        self.calls.append(("rollback", "", ()))

    def savepoint(self, name: str) -> None:
        self.calls.append(("savepoint", name, ()))

    def release_savepoint(self, name: str) -> None:
        self.calls.append(("release_savepoint", name, ()))

    def rollback_to_savepoint(self, name: str) -> None:
        self.calls.append(("rollback_to_savepoint", name, ()))

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def inner() -> _FakeDriver:
    """Inner driver that the decorator wraps."""
    return _FakeDriver()


def test_a_decorated_driver_is_still_a_driver(inner: _FakeDriver) -> None:
    """Verifies the contract: wrapping cannot break the Protocol, or it would be worth nothing."""
    assert isinstance(LoggingDriver(inner), SnakeDriver)


def test_it_passes_everything_through_untouched(inner: _FakeDriver) -> None:
    """Verifies that the decorator does NOT alter the SQL, the params or the returned value."""
    driver = LoggingDriver(inner)

    assert driver.fetch_all("SELECT 1", (7,)) == [(1, "Ana")]
    assert driver.execute("DELETE FROM t WHERE id = %s", (7,)) == 3

    assert inner.calls[0] == ("fetch_all", "SELECT 1", (7,))
    assert inner.calls[1] == ("execute", "DELETE FROM t WHERE id = %s", (7,))


def test_it_logs_the_sql_and_its_parameters(inner: _FakeDriver) -> None:
    """Verifies that the emitted SQL is visible: debugging an ORM blindfolded is masochism.

    The VALUES are a separate decision from the statement, and this test used to conflate them by
    asserting `(7,)` in the default output. The statement is safe by construction —the ORM never
    interpolates— and the values are the only thing that can carry user data, so they are opt-in.
    Both halves are asserted here so neither can drift into the other.
    """
    written: list[str] = []
    driver = LoggingDriver(inner, write=written.append)

    driver.execute("DELETE FROM t WHERE id = %s", (7,))

    assert len(written) == 1
    assert "DELETE FROM t WHERE id = %s" in written[0]
    assert "7" not in written[0].split("params=")[1].split(" -> ")[0], (
        "the value went out without anyone asking for it"
    )
    assert "<1 hidden>" in written[0]

    asked: list[str] = []
    LoggingDriver(inner, write=asked.append, parameter_keys=frozenset({"0"})).execute(
        "DELETE FROM t WHERE id = %s", (7,)
    )

    assert "(7)" in asked[0]


def test_it_reports_the_row_count_and_the_rows_read(inner: _FakeDriver) -> None:
    """Verifies that the log says HOW MUCH each statement did, which is half the information."""
    written: list[str] = []
    driver = LoggingDriver(inner, write=written.append)

    driver.execute("DELETE FROM t WHERE id = %s", (7,))
    driver.fetch_all("SELECT 1", ())

    assert "3 row(s)" in written[0]
    assert "1 row(s)" in written[1]


def test_transaction_boundaries_are_logged_too(inner: _FakeDriver) -> None:
    """Verifies that commit/rollback/savepoint show up too: without them the log lies by omission."""
    written: list[str] = []
    driver = LoggingDriver(inner, write=written.append)

    driver.commit()
    driver.rollback()
    driver.savepoint("sp1")

    assert [line.split()[0] for line in written] == ["COMMIT", "ROLLBACK", "SAVEPOINT"]


def test_closing_the_wrapper_closes_the_inner_driver(inner: _FakeDriver) -> None:
    """Verifies that the decorator does not keep the connection: closing means really closing."""
    LoggingDriver(inner).close()
    assert inner.closed is True


def test_logging_is_off_by_default(inner: _FakeDriver) -> None:
    """Verifies that with no `write` nothing is written: the decorator can stay on and keep quiet."""
    driver = LoggingDriver(inner)
    driver.execute("SELECT 1", ())
    assert inner.calls  # it reached the inner driver, simply without the noise


def test_the_values_do_not_reach_the_log_by_default(inner: _FakeDriver) -> None:
    """The parameters are HIDDEN unless asked for, key by key. The count still shows.

    The guide tells you to wire this with `write=print` in production, and `print` goes to the
    container's stdout, which goes to the log aggregator. So a `session.add(User(email=...,
    password_hash=...))` used to put both in there, in the clear, with no flag to stop it.

    The count is kept —`<2 hidden>` and not a blanked-out blob— because it hides nothing: knowing a
    statement carried two parameters is half of what makes a log line readable, and it is the half
    that cannot leak.
    """
    written: list[str] = []
    driver = LoggingDriver(inner, write=written.append)

    driver.execute(
        "INSERT INTO users (email, pw) VALUES (%s, %s)", ("ana@x.com", "$2b$12$hash")
    )

    assert "ana@x.com" not in written[0]
    assert "$2b$12$hash" not in written[0]
    assert "<2 hidden>" in written[0]
    assert "INSERT INTO users" in written[0], "the statement itself is not secret"


def test_a_named_parameter_is_shown_and_the_rest_stay_hidden(
    inner: _FakeDriver,
) -> None:
    """`parameter_keys` names positions by 0-based index, exactly as the otel exporter does.

    Same spelling, same type, same key convention: this is the SECOND consumer of a policy this
    repo already reasoned through, not a second policy. And there is NO environment variable, which
    is the part of it that matters — an environment variable is precisely the switch somebody flips
    in production by accident.
    """
    written: list[str] = []
    driver = LoggingDriver(inner, write=written.append, parameter_keys=frozenset({"0"}))

    driver.execute(
        "INSERT INTO users (email, pw) VALUES (%s, %s)", ("ana@x.com", "$2b$12$hash")
    )

    assert "ana@x.com" in written[0]
    assert "$2b$12$hash" not in written[0]


def test_there_is_no_environment_variable_for_the_parameters() -> None:
    """Neither logging module reads the environment to decide whether to print user values.

    Asserted over the parsed source rather than by grepping for a word: `os.environ`/`os.getenv` are
    the two ways to reach it, and a substring search for "environ" trips over the prose in the very
    docstrings that explain the policy.
    """
    import ast
    import inspect

    from snakeorm.drivers import asyncdecorators, logging as logging_driver

    for module in (logging_driver, asyncdecorators):
        tree = ast.parse(inspect.getsource(module))
        reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr in {"environ", "getenv"}
        ]
        assert reads == [], (
            f"{module.__name__} reads the environment to decide what to log"
        )


class _Exploding:
    """A driver whose `execute` raises, which is what a constraint violation looks like from here."""

    def __init__(self) -> None:
        self.rows: list[tuple[object, ...]] = [(1,)]

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        raise RuntimeError("duplicate key value violates unique constraint")

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        yield from self.rows

    def execute(self, sql: str, params: Sequence[object]) -> int:
        raise RuntimeError("duplicate key value violates unique constraint")

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


def test_a_statement_that_fails_still_reaches_the_log() -> None:
    """The one line you were looking for was the one line that never got written.

    `execute` logged AFTER the inner call returned, so a statement that raised produced nothing at
    all. You open the log at 3:14, find the ten statements before it and a ROLLBACK —that one wrote,
    because `rollback()` follows a call that does not fail— and no trace of what caused the
    rollback. The log shows you everything except the thing you came for.

    And the exception does not carry it either: `drivers/failures.py` builds its message from the
    engine's words, with no SQL and no params in it. The log WAS the only place the failed statement
    existed.
    """
    written: list[str] = []
    driver = LoggingDriver(_Exploding(), write=written.append)

    with pytest.raises(RuntimeError):
        driver.execute("INSERT INTO users (email) VALUES (%s)", ("ana@x.com",))

    assert len(written) == 1, "the failing statement left no line at all"
    assert "INSERT INTO users" in written[0]
    assert "FAILED" in written[0]
    assert "RuntimeError" in written[0]


def test_a_failing_read_also_reaches_the_log() -> None:
    """Same for `fetch_all`: the seven other write points had the same shape as `execute`."""
    written: list[str] = []
    driver = LoggingDriver(_Exploding(), write=written.append)

    with pytest.raises(RuntimeError):
        driver.fetch_all("SELECT * FROM missing", ())

    assert "FAILED" in written[0]


def test_a_consumer_that_breaks_out_of_a_stream_is_not_a_failure(
    inner: _FakeDriver,
) -> None:
    """`fetch_iter` is left ALONE, and this test is why.

    Wrapping it like its neighbours would catch the `GeneratorExit` that a `break` raises inside a
    generator and write the streaming down as FAILED — breaking the one method of the nine that
    already had the right shape (`try/finally`), in exactly the case its own docstring names.

    Deleting the special case is not always the right move: here the special case was the only
    correct one, and the eight neighbours were the exception.
    """
    written: list[str] = []
    driver = LoggingDriver(inner, write=written.append)

    for _row in driver.fetch_iter("SELECT 1", ()):
        break

    assert written, "the stream logged nothing at all"
    assert "FAILED" not in written[-1], "a `break` was written down as a failure"
    assert "streamed" in written[-1]
