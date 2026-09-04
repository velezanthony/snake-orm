"""Tests that BOTH sessions run the SAME plan, not two implementations that merely look alike.

The parity test that already existed compares the SURFACE: that both expose the same methods. That
catches a missing one, but not that they do different things — and that had already happened: the
docstring of `AsyncSession.add` swore it built its plan with `planning.plan_insert`, "the same one as
the synchronous session", while the synchronous one emitted on its own with `emit_insert`. The
documentation described a sharing that did not exist, and no test noticed.

What is checked here is the SQL that comes out through the driver. It is the one thing that cannot
be faked: if either of the two changes path, the two SQLs stop matching and this falls over.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Sequence

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeRow,
    snake_auto,
    snake_model,
    snake_row,
    snake_str,
)
from snakeorm.core.exceptions import SnakeError

from snakeorm.dialects import SQLiteDialect
from snakeorm.query import SnakeQuery
from snakeorm.session import AsyncSession, SnakeSession
from snakeorm.session.isolation import SnakeIsolation


@snake_model(table="plan_sharing_widgets")
class Widget(SnakeModel):
    """Minimal model: what is compared is the SQL, not the domain."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()


class _Recorder:
    """Synchronous driver that records the `(sql, params)` of everything passing through it."""

    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.seen: list[tuple[str, tuple[object, ...]]] = []
        self._rows: list[tuple[object, ...]] = rows if rows is not None else [(1, "x")]

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.seen.append((sql, tuple(params)))
        return self._rows

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.seen.append((sql, tuple(params)))
        return 1

    @property
    def last_insert_id(self) -> int:
        return 1

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


class _AsyncRecorder:
    """The same recorder, awaiting. An exact mirror so that the comparison is a fair one."""

    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.seen: list[tuple[str, tuple[object, ...]]] = []
        self._rows: list[tuple[object, ...]] = rows if rows is not None else [(1, "x")]

    async def fetch_all(
        self, sql: str, params: Sequence[object]
    ) -> list[tuple[object, ...]]:
        self.seen.append((sql, tuple(params)))
        return self._rows

    async def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> AsyncIterator[tuple[object, ...]]:
        for row in await self.fetch_all(sql, params):
            yield row

    async def execute(self, sql: str, params: Sequence[object]) -> int:
        self.seen.append((sql, tuple(params)))
        return 1

    @property
    def last_insert_id(self) -> int:
        """The id of the last INSERT. Engines with RETURNING do not use it (see the Protocol)."""
        return 0

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def savepoint(self, name: str) -> None: ...
    async def release_savepoint(self, name: str) -> None: ...
    async def rollback_to_savepoint(self, name: str) -> None: ...
    async def close(self) -> None: ...


def _both(sync_call, async_call) -> tuple[list, list]:  # type: ignore[no-untyped-def]
    """Runs the same operation on both sessions and returns what each driver saw."""
    sync_driver, async_driver = _Recorder(), _AsyncRecorder()
    sync_call(SnakeSession(sync_driver, SQLiteDialect()))
    asyncio.run(async_call(AsyncSession(async_driver, SQLiteDialect())))
    return sync_driver.seen, async_driver.seen


def test_add_emits_the_same_sql_in_both_sessions() -> None:
    """Verifies that the INSERT is identical in both.

    It is the case where the drift was real: the async one used `plan_insert` and the synchronous
    one emitted by hand. A change in the plan (the polymorphic discriminator, say) reached only one.
    """
    sync_seen, async_seen = _both(
        lambda s: s.add(Widget(name="a")),
        lambda s: s.add(Widget(name="a")),
    )
    assert sync_seen == async_seen


def test_count_emits_the_same_sql_in_both_sessions() -> None:
    """Verifies that the COUNT comes out through the same scalar plan in both."""
    query = SnakeQuery(Widget).filter(Widget.name == "a")
    sync_seen, async_seen = _both(
        lambda s: s.count(query),
        lambda s: s.count(query),
    )
    assert sync_seen == async_seen


def test_exists_emits_the_same_sql_in_both_sessions() -> None:
    """Verifies that the EXISTS shares its plan too."""
    query = SnakeQuery(Widget).filter(Widget.name == "a")
    sync_seen, async_seen = _both(
        lambda s: s.exists(query),
        lambda s: s.exists(query),
    )
    assert sync_seen == async_seen


def test_all_emits_the_same_sql_in_both_sessions() -> None:
    """Verifies that the plain read matches (the base everything else leans on)."""
    query = SnakeQuery(Widget).order_by(Widget.name).limit(10)
    sync_seen, async_seen = _both(
        lambda s: s.all(query),
        lambda s: s.all(query),
    )
    assert sync_seen == async_seen


def test_iterate_emits_the_same_sql_in_both_sessions() -> None:
    """Verifies that streaming, the latest addition, is born free of drift already."""
    query = SnakeQuery(Widget).limit(5)

    async def consumir(session: AsyncSession) -> None:
        async for _ in session.iterate(query, chunk=7):
            pass

    sync_seen, async_seen = _both(
        lambda s: list(s.iterate(query, chunk=7)),
        consumir,
    )
    assert sync_seen == async_seen


def _error_from(operation, *, is_async: bool) -> str:  # type: ignore[no-untyped-def]
    """The MESSAGE of the error that operation raises on the session asked for.

    It catches `SnakeError` and not `SnakeEmitError`: the question this helper asks is "do the two
    colours complain with the same words", and narrowing it to one exception class made it usable
    for exactly one kind of complaint. The refusals that come from the CAPABILITY catalogue —where
    the two colours had drifted apart hardest— could not be asked at all.
    """
    if is_async:
        session = AsyncSession(
            _AsyncRecorder(rows=[(1, "x", "extra")]), SQLiteDialect()
        )
        try:
            asyncio.run(operation(session))
        except SnakeError as error:
            return str(error)
    else:
        sync_session = SnakeSession(
            _Recorder(rows=[(1, "x", "extra")]), SQLiteDialect()
        )
        try:
            operation(sync_session)
        except SnakeError as error:
            return str(error)
    raise AssertionError("the operation had to fail and did not")


@snake_row
class _DosColumnas(SnakeRow):
    """A declared shape of two columns, to provoke the mismatch against a row of three."""

    id: int
    name: str


def test_raw_explains_a_shape_mismatch_with_the_SAME_words_in_both_sessions() -> None:
    """Verifies that the MESSAGE matches, not only the SQL.

    This is the half that was missing and through which the drift slipped in. The parity test
    compared the emitted SQL, so two implementations producing the same SELECT and explaining the
    failure with different words passed green for months.

    In an ORM whose doctrine is to SHOUT, the message IS the product: if it diverges, so does the
    product.
    """
    sincrono = _error_from(
        lambda s: s.raw("SELECT 1", into=_DosColumnas), is_async=False
    )
    asincrono = _error_from(
        lambda s: s.raw("SELECT 1", into=_DosColumnas), is_async=True
    )

    assert sincrono == asincrono


def test_call_names_the_routine_the_same_way_in_both_sessions() -> None:
    """Verifies the concrete case that HAD already diverged: "La función" against "La rutina".

    It was born when the helper was extracted: `f0e30fc` rewrote the message instead of moving it,
    and the synchronous one was left with the old text. A test comparing SQL cannot see that.
    """
    sincrono = _error_from(lambda s: s.call("f", (), into=_DosColumnas), is_async=False)
    asincrono = _error_from(lambda s: s.call("f", (), into=_DosColumnas), is_async=True)

    assert sincrono == asincrono


def test_set_isolation_refuses_with_the_SAME_words_in_both_sessions() -> None:
    """SQLite cannot set an isolation level, and BOTH colours have to say so the same way.

    The synchronous one asks the catalogue and raises `SnakeUnsupportedFeature`. The asynchronous
    one handed `SET TRANSACTION ISOLATION LEVEL ...` straight to the driver, so SQLite answered
    `OperationalError: near "SET": syntax error` — which is, word for word, the failure the
    synchronous docstring says it exists to prevent. The fix had been applied to one colour.

    Emitting engine SQL from the session without asking is also the thing the dialect seam exists to
    stop, so this is not only a parity bug: the asynchronous session was reaching past the seam.
    """
    sincrono = _error_from(
        lambda s: s.set_isolation(SnakeIsolation.SERIALIZABLE), is_async=False
    )
    asincrono = _error_from(
        lambda s: s.set_isolation(SnakeIsolation.SERIALIZABLE), is_async=True
    )

    assert sincrono == asincrono
