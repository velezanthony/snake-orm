"""`AsyncSession`: the same session, awaited.

What gets checked here is not that "async works": it is that it **emits EXACTLY the same SQL** as
the synchronous one. That is the proof of decision D3 — if the two sessions made their decisions
separately, they would diverge, and diverging means having two places to fix every bug.

It runs against a double driver, with no server: what gets measured is the DECISION, and the
decision does not depend on the engine.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from snakeorm import (
    PostgresDialect,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SnakeToOne,
    snake_int,
    snake_model,
    snake_to_one,
)
from snakeorm.session import AsyncSession
from snakeorm.core.signals import SnakeSignal, disconnect_all, snake_on

_DIALECT = PostgresDialect()


@snake_model(table="asy_customers")
class Customer(SnakeModel):
    """Target of the relationship: needed to test that `include` is rejected."""

    id: SnakeColumn[int] = snake_int(primary_key=True)


@snake_model(table="asy_orders")
class Order(SnakeModel):
    """Minimal model for comparing the two sessions."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    amount: SnakeColumn[int] = snake_int()
    customer_id: SnakeColumn[int] = snake_int()
    customer: SnakeToOne[Customer] = snake_to_one(customer_id)


class _DriverSync:
    """Fake synchronous driver that writes down the SQL that was emitted."""

    def __init__(self) -> None:
        self.sql: list[str] = []
        self.params: list[tuple[object, ...]] = []

    def fetch_all(self, sql: str, params: object = ()) -> list[tuple[object, ...]]:
        self.sql.append(sql)
        self.params.append(tuple(params))  # type: ignore[arg-type]
        return [(1, 100, 1)]

    def execute(self, sql: str, params: object = ()) -> int:
        self.sql.append(sql)
        self.params.append(tuple(params))  # type: ignore[arg-type]
        return 1

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class _DriverAsync:
    """The SAME double, but asynchronous: same records, with `await`."""

    def __init__(self) -> None:
        self.sql: list[str] = []
        self.params: list[tuple[object, ...]] = []

    async def fetch_all(
        self, sql: str, params: object = ()
    ) -> list[tuple[object, ...]]:
        self.sql.append(sql)
        self.params.append(tuple(params))  # type: ignore[arg-type]
        return [(1, 100, 1)]

    async def execute(self, sql: str, params: object = ()) -> int:
        self.sql.append(sql)
        self.params.append(tuple(params))  # type: ignore[arg-type]
        return 1

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def close(self) -> None: ...


@pytest.fixture(autouse=True)
def without_handlers() -> Iterator[None]:
    """Signals live in a global dict: they get cleaned up between tests."""
    disconnect_all()
    yield
    disconnect_all()


def _sync(action: object) -> _DriverSync:
    """Runs an action against the synchronous session and returns its driver."""
    driver = _DriverSync()
    session = SnakeSession(driver, _DIALECT)  # type: ignore[arg-type]
    action(session)  # type: ignore[operator]
    return driver


def _async(action: object) -> _DriverAsync:
    """Runs the equivalent action against the asynchronous session and returns its driver."""
    driver = _DriverAsync()
    session = AsyncSession(driver, _DIALECT)  # type: ignore[arg-type]
    asyncio.run(action(session))  # type: ignore[operator]
    return driver


def test_add_emits_the_same_sql_in_both_sessions() -> None:
    """THE proof of decision D3: the same operation, the same SQL, the same params.

    If they diverged, every bug would have two places to be fixed in — which is the bet this branch
    has already lost three times with other sibling surfaces.
    """
    sync_driver = _sync(lambda s: s.add(Order(id=1, amount=100, customer_id=1)))

    async def async_action(s: AsyncSession) -> None:
        await s.add(Order(id=1, amount=100, customer_id=1))

    async_driver = _async(async_action)

    assert async_driver.sql == sync_driver.sql
    assert async_driver.params == sync_driver.params


def test_a_query_emits_the_same_sql_in_both_sessions() -> None:
    """The query compiles with the SAME code: `to_sql()` has no color."""
    query = SnakeQuery(Order).filter(Order.amount > 50).order_by(Order.id.asc())
    sync_driver = _sync(lambda s: s.all(query))

    async def async_action(s: AsyncSession) -> None:
        await s.all(query)

    assert _async(async_action).sql == sync_driver.sql


def test_delete_emits_the_same_sql_in_both_sessions() -> None:
    """Likewise for deletion by PK."""
    sync_driver = _sync(lambda s: s.delete(Order(id=1, amount=100, customer_id=1)))

    async def async_action(s: AsyncSession) -> None:
        await s.delete(Order(id=1, amount=100, customer_id=1))

    assert _async(async_action).sql == sync_driver.sql


def test_the_async_session_fires_the_same_signals() -> None:
    """Signals fire in async too, and in the same order.

    A feature that existed only in the synchronous session would be exactly the bug this project
    keeps chasing: implemented in one of two siblings.
    """
    seen: list[str] = []

    @snake_on(Order, SnakeSignal.PRE_SAVE)
    def before(order: Order) -> None:
        """Writes down the PRE."""
        seen.append("pre")

    @snake_on(Order, SnakeSignal.POST_SAVE)
    def after(order: Order) -> None:
        """Writes down the POST."""
        seen.append("post")

    async def async_action(s: AsyncSession) -> None:
        await s.add(Order(id=1, amount=100, customer_id=1))

    _async(async_action)

    assert seen == ["pre", "post"]


def test_the_returned_row_lands_in_the_instance() -> None:
    """`RETURNING` is applied the same way: the object comes back with what the server put in."""

    async def async_action(s: AsyncSession) -> None:
        order = Order(id=1, amount=0, customer_id=1)
        await s.add(order)
        assert order.amount == 100, "the double returns 100: it has to reach the object"

    _async(async_action)


def test_both_sessions_expose_the_same_surface() -> None:
    """THE list, checked by the ORM and not by my memory.

    This test exists because the first version of `AsyncSession` shipped 12 of the synchronous
    one's 22 methods, and the commit that delivered it said —literally— that a feature present in
    only one of two siblings would be the bug this project keeps chasing. Recognizing the pattern
    does not vaccinate you against it; the only thing that vaccinates is having the machine do the
    checking.

    Methods that make NO sense on the other side are excluded on purpose, and every exclusion is
    justified here: if tomorrow somebody removes one, this test will say so.
    """
    import ast
    import pathlib

    def public_methods(path: str, class_name: str) -> set[str]:
        """Public methods declared in that class."""
        tree = ast.parse(pathlib.Path(path).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return {
                    child.name
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not child.name.startswith("_")
                }
        raise AssertionError(f"{class_name} was not found")

    # There are no exclusions any more: the two sessions expose exactly the same thing. If one
    # were needed tomorrow, it gets added HERE with its reason written down, not in production code.
    SYNC_ONLY: set[str] = set()

    sync_methods = public_methods("src/snakeorm/session/session.py", "SnakeSession")
    async_methods = public_methods(
        "src/snakeorm/session/asyncsession.py", "AsyncSession"
    )

    missing = sync_methods - async_methods - SYNC_ONLY
    assert missing == set(), f"the async session does not expose: {sorted(missing)}"


def test_both_sessions_type_their_methods_the_same_way() -> None:
    """The same NAME is not enough: the same return TYPE and the same `into` type.

    This check did not exist, and its absence cost a real bug: `AsyncSession.call/raw` returned
    `list[Any]` while the synchronous ones returned `list[Row]`. The previous net compares
    `child.name` —it enumerates the surface and asserts on NAMES— so `list[Any]` passed green saying
    'same surface'. In the project whose entire thesis is typing, the async half switched it off in
    two methods, and worse: the `Any` disabled the `Row: SnakeRow` bound, the read-only lock.

    What gets compared is the textual AST annotations of the methods that share a name. `self` and
    the expected differences (`async def`, one extra `await`) do not change the signatures; an `Any`
    where the sibling puts a TypeVar does.
    """
    import ast
    import pathlib

    def signatures(path: str, class_name: str) -> dict[str, tuple[str, str]]:
        """(return, type of `into`) per public method, as AST text."""
        tree = ast.parse(pathlib.Path(path).read_text())
        out: dict[str, tuple[str, str]] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef) and node.name == class_name):
                continue
            for child in node.body:
                if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if child.name.startswith("_"):
                    continue
                return_type = ast.unparse(child.returns) if child.returns else ""
                # The ONLY legitimate type difference between the two: an async context manager
                # returns `AsyncIterator` where the synchronous one returns `Iterator`. It gets
                # normalized so the test does not flag it, and so what stays flagged is ALWAYS one
                # `Any` too many.
                return_type = return_type.replace("AsyncIterator", "Iterator")
                into = next(
                    (
                        ast.unparse(a.annotation)
                        for a in child.args.kwonlyargs
                        if a.arg == "into" and a.annotation is not None
                    ),
                    "",
                )
                out[child.name] = (return_type, into)
        return out

    sync = signatures("src/snakeorm/session/session.py", "SnakeSession")
    asyn = signatures("src/snakeorm/session/asyncsession.py", "AsyncSession")

    diverging = {
        name: {"sync": sync[name], "async": asyn[name]}
        for name in sync.keys() & asyn.keys()
        if sync[name] != asyn[name]
    }

    assert diverging == {}, (
        f"these methods are typed differently in the two sessions: {diverging}. An `Any` where the "
        f"sibling puts a concrete type is the project thesis switched off in the async half."
    )


def test_the_async_decorators_wrap_without_the_session_noticing() -> None:
    """The async decorators wrap just like the synchronous ones: the session never notices.

    It is the property that makes driver decorators useful — if the session had to know there is one
    in front of it, they would stop being decorators and become one more branch.
    """
    from snakeorm import AsyncLoggingDriver

    lines: list[str] = []
    driver = _DriverAsync()
    session = AsyncSession(AsyncLoggingDriver(driver, write=lines.append), _DIALECT)  # type: ignore[arg-type]

    async def work() -> None:
        await session.add(Order(id=1, amount=100, customer_id=1))
        await session.commit()

    asyncio.run(work())

    assert any("INSERT INTO" in line for line in lines)
    assert any("ms" in line for line in lines), "and it records the duration"
    assert lines[-1] == "COMMIT"


def test_the_timeout_decorator_applies_the_limit_on_connect() -> None:
    """`AsyncTimeoutDriver.apply_to` leaves `statement_timeout` set on the connection.

    It is applied on connect and not in the constructor because in async you cannot await inside an
    `__init__`. Pretending you can —by firing off a loose task— would leave a moment in which the
    driver claims to have a timeout without having one yet.
    """
    from snakeorm import AsyncTimeoutDriver

    driver = _DriverAsync()

    async def work() -> None:
        await AsyncTimeoutDriver.apply_to(
            driver,  # type: ignore[arg-type]  # a double, not a full AsyncDriver
            PostgresDialect(),
            statement_timeout_ms=5000,
        )

    asyncio.run(work())

    assert driver.sql == ["SET statement_timeout = 5000"]


def test_the_async_log_writes_the_savepoint_boundaries_too() -> None:
    """The three savepoint methods wrote NOTHING. A log without the boundaries lies by omission.

    That phrase is the synchronous twin's own docstring, and this colour omitted three of the
    boundaries it names — so an async session's log showed the statements inside a savepoint with no
    sign that a savepoint existed, and a `rollback_to` that undid them left no trace at all.
    """
    from snakeorm import AsyncLoggingDriver

    class _Marks:
        """A driver that accepts the three savepoint calls and does nothing else."""

        async def savepoint(self, name: str) -> None: ...
        async def release_savepoint(self, name: str) -> None: ...
        async def rollback_to_savepoint(self, name: str) -> None: ...

    lines: list[str] = []
    driver = AsyncLoggingDriver(_Marks(), write=lines.append)  # type: ignore[arg-type]

    async def work() -> None:
        await driver.savepoint("sp1")
        await driver.release_savepoint("sp1")
        await driver.rollback_to_savepoint("sp1")

    asyncio.run(work())

    assert lines == [
        "SAVEPOINT sp1",
        "RELEASE SAVEPOINT sp1",
        "ROLLBACK TO SAVEPOINT sp1",
    ]


def test_the_async_log_does_not_write_the_values_either() -> None:
    """The parameter policy is the SAME in both colours, and it was fixed in only one.

    The synchronous driver stopped printing user values; this one carried on. Two classes, one
    decision, and the decision applied to half of it — which is the drift this seam keeps suffering
    and the reason the renderer now lives in one place.
    """
    from snakeorm import AsyncLoggingDriver

    lines: list[str] = []
    driver = AsyncLoggingDriver(_DriverAsync(), write=lines.append)  # type: ignore[arg-type]

    async def work() -> None:
        await driver.execute("INSERT INTO users (email) VALUES (?)", ("ana@x.com",))

    asyncio.run(work())

    assert "ana@x.com" not in lines[0]
    assert "<1 hidden>" in lines[0]


def test_a_failing_async_statement_reaches_the_log_with_its_timing() -> None:
    """The failing case is where the elapsed time is MOST interesting, and it was the one lost.

    A statement that took four seconds and then died is the line you are looking for; the write
    sat after the awaited call, so it never happened.
    """
    from snakeorm import AsyncLoggingDriver

    class _Boom:
        async def execute(self, sql: str, params: object) -> int:
            raise RuntimeError("deadlock detected")

    lines: list[str] = []
    driver = AsyncLoggingDriver(_Boom(), write=lines.append)  # type: ignore[arg-type]

    async def work() -> None:
        await driver.execute("UPDATE t SET a = 1", ())

    with pytest.raises(RuntimeError):
        asyncio.run(work())

    assert "FAILED" in lines[0]
    assert "deadlock detected" in lines[0]
    assert "ms" in lines[0], (
        "the duration of the failing statement is the interesting one"
    )
