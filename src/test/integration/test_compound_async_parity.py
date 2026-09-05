"""The SAME set operation down the two colours, on the three engines: same rows, same refusal.

Every defect found in `SnakeCompound` so far came out of the synchronous session. The asynchronous
one is not a second implementation — the SQL has no colour and both sessions consume the same
`to_sql` — but that is an argument, and the repo has already been shown an argument like it failing:
the two halves drifted on the WORDING of a complaint while the SQL stayed identical, and the test
that only compared SQL let it through for months.

So this compares three things per engine: the rows a compound answers, the rows a NARROWED compound
answers (that was the tanda-1 bug, and it lived in the hydration each session does for itself), and
the exact TEXT of the refusal where the engine cannot express the query.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import Any, TypeVar

import pytest

from snakeorm import (
    AsyncPsycopgDriver,
    AsyncPyMySQLDriver,
    AsyncSession,
    AsyncSQLiteDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
)
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.drivers.asyncbase import AsyncDriver
from snakeorm.query.compound import SnakeCompoundBranch
from test.scenarios.db import dsn
from test.scenarios.engines import DIALECTS, mysql_kwargs, three_sessions

pytest.importorskip(
    "psycopg",
    reason="the async path needs psycopg 3: install `snakeorm[async]`",
)

pytestmark = pytest.mark.integration

T = TypeVar("T")


@snake_model(table="asyncpar_rows")
class ParityRow(SnakeModel):
    """A different value per column, so a projection lined up wrong is VISIBLE in the rows."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    tag: SnakeColumn[str] = snake_str(max_length=8)
    amount: SnakeColumn[int] = snake_int()


snake_link()

_ROWS = ((1, "alfa", 100), (2, "bravo", 500), (3, "charlie", 500), (4, "delta", 900))


def _run(work: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Runs a coroutine in a loop of its own. `Coroutine` because `asyncio.run` demands one."""
    return asyncio.run(work())


@pytest.fixture(scope="module")
def sqlite_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A SQLite FILE, not `:memory:`: the two colours are two connections to one database."""
    return tmp_path_factory.mktemp("asyncpar") / "parity.db"


@pytest.fixture(scope="module")
def engines(sqlite_file: Path) -> Iterator[dict[str, SnakeSession]]:
    """The three SYNCHRONOUS sessions, seeded and committed so the async ones can read them."""
    with three_sessions([ParityRow], str(sqlite_file)) as sessions:
        for session in sessions.values():
            session.add_all([ParityRow(id=i, tag=t, amount=a) for i, t, a in _ROWS])
            session.commit()
        yield sessions


async def _open_async(name: str, sqlite_file: Path) -> AsyncDriver:
    """The asynchronous driver of one engine, pointed at the same database as its twin."""
    if name == "sqlite":
        return await AsyncSQLiteDriver.connect(str(sqlite_file))
    if name == "postgres":
        return await AsyncPsycopgDriver.connect(dsn())
    return await AsyncPyMySQLDriver.connect(**mysql_kwargs())  # type: ignore[arg-type]


async def _async_answer(
    name: str,
    sqlite_file: Path,
    build: Callable[[], SnakeCompoundBranch[ParityRow]],
) -> list[tuple[int, str, int]] | str:
    """What the ASYNC session answers on one engine: the rows, or the refusal's exact text."""
    driver = await _open_async(name, sqlite_file)
    try:
        session = AsyncSession(driver, DIALECTS[name])
        rows = await session.all(build())
        return sorted((row.id, row.tag, row.amount) for row in rows)
    except SnakeEmitError as error:
        return str(error)
    finally:
        await driver.close()


def _sync_answer(
    session: SnakeSession, build: Callable[[], SnakeCompoundBranch[ParityRow]]
) -> list[tuple[int, str, int]] | str:
    """The same, from the SYNCHRONOUS session. Identical shape, so the two are comparable."""
    try:
        return sorted((row.id, row.tag, row.amount) for row in session.all(build()))
    except SnakeEmitError as error:
        return str(error)


def _both_colours(
    engines: dict[str, SnakeSession],
    sqlite_file: Path,
    build: Callable[[], SnakeCompoundBranch[ParityRow]],
) -> dict[str, tuple[object, object]]:
    """Per engine, what each colour answered. Comparing the pair IS the test."""
    answers: dict[str, tuple[object, object]] = {}
    for name, session in engines.items():

        async def read(engine: str = name) -> list[tuple[int, str, int]] | str:
            return await _async_answer(engine, sqlite_file, build)

        answers[name] = (_sync_answer(session, build), _run(read))
    return answers


def _low() -> SnakeQuery[ParityRow]:
    """Rows 1, 2 and 3."""
    return SnakeQuery(ParityRow).filter(ParityRow.amount <= 500)


def _high() -> SnakeQuery[ParityRow]:
    """Rows 2, 3 and 4."""
    return SnakeQuery(ParityRow).filter(ParityRow.amount >= 500)


def test_a_set_answers_the_same_rows_down_both_colours_on_the_three_engines(
    engines: dict[str, SnakeSession], sqlite_file: Path
) -> None:
    """`UNION ALL` gives the same rows to `SnakeSession` and to `AsyncSession`, engine by engine.

    Whole tuples and not ids: a value landing on the wrong attribute keeps the id intact, so a test
    that only counted rows or read the key would agree with a wrecked instance.
    """
    answers = _both_colours(engines, sqlite_file, lambda: _low().union_all(_high()))

    for name, (sync, asyn) in answers.items():
        assert sync == asyn, f"{name} answers differently by colour: {sync} vs {asyn}"
    assert answers["postgres"][0] == [
        (1, "alfa", 100),
        (2, "bravo", 500),
        (2, "bravo", 500),
        (3, "charlie", 500),
        (3, "charlie", 500),
        (4, "delta", 900),
    ]


def test_a_narrowed_set_hydrates_the_same_fields_down_both_colours(
    engines: dict[str, SnakeSession], sqlite_file: Path
) -> None:
    """`only()` on both branches: each colour narrows its own plan, so each could get it wrong alone.

    This is the shape that already broke once — the values of a narrowed branch landing on the wrong
    attributes — and the narrowing is written out twice, once per session, because `await` is syntax
    and one body cannot serve both colours.
    """

    def narrowed() -> SnakeCompoundBranch[ParityRow]:
        return _low().only(ParityRow.tag).union(_high().only(ParityRow.tag))

    answers: dict[str, tuple[list[tuple[int, str]], list[tuple[int, str]]]] = {}
    for name, session in engines.items():
        sync_rows = sorted((row.id, row.tag) for row in session.all(narrowed()))
        answers[name] = (
            sync_rows,
            _run(_narrowed_reader(name, sqlite_file)),
        )

    for name, (sync, asyn) in answers.items():
        assert sync == asyn, f"{name} hydrates differently by colour: {sync} vs {asyn}"
    assert answers["postgres"][0] == [
        (1, "alfa"),
        (2, "bravo"),
        (3, "charlie"),
        (4, "delta"),
    ]


def _narrowed_reader(
    name: str, sqlite_file: Path
) -> Callable[[], Coroutine[Any, Any, list[tuple[int, str]]]]:
    """The narrowed set read by the ASYNC session, as a coroutine factory `_run` can take."""

    async def read() -> list[tuple[int, str]]:
        driver = await _open_async(name, sqlite_file)
        try:
            session = AsyncSession(driver, DIALECTS[name])
            rows = await session.all(
                _low().only(ParityRow.tag).union(_high().only(ParityRow.tag))
            )
            return sorted((row.id, row.tag) for row in rows)
        finally:
            await driver.close()

    return read


def test_a_refusal_reaches_both_colours_with_the_SAME_words(
    engines: dict[str, SnakeSession], sqlite_file: Path
) -> None:
    """Where an engine cannot express the set, both sessions refuse — and say the same sentence.

    Comparing the text and not just the exception type is the whole point. The drift that already
    happened here was one complaint told two ways, and a test that compared only the SQL passed
    through it. In an ORM whose doctrine is to shout, the message IS the product.
    """
    answers = _both_colours(
        engines, sqlite_file, lambda: _low().except_(_high().union(_low()))
    )

    sync, asyn = answers["sqlite"]
    assert isinstance(sync, str) and sync == asyn
    assert "reads the operators left to right" in sync
    for name in ("postgres", "mysql"):
        assert answers[name][0] == answers[name][1] == []
