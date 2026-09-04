"""Bringing HALF a row: `only()` names what to load, `defer()` names what to leave.

The volume tables are where this is worth having. A visits table carries a `user_agent` that a
traffic report never prints, and the whole of it travels on every row anyway. What `only()` buys is
the bytes; what it COSTS is an instance that is not whole, and this file is mostly about that cost.

WHY THE UNLOADED COLUMN HAS TO RAISE, AND WHY IT WAS NOT GOING TO. The column descriptor's
instance-side `__get__` reads `getattr(instance, key, self.default)`. An attribute that was never
written falls through to the DEFAULT, so a naive `only()` would hand back `None` for a name nobody
loaded — a wrong answer with no error, which is the one outcome this ORM's doctrine forbids. So
hydration writes a SENTINEL for every column left out, and the descriptor tells it apart from both a
real value and an instance the user built by hand.

THE THREE STATES ARE THE WHOLE DIFFICULTY. `__get__` has to distinguish a value, a column
deliberately left out, and an attribute simply never set on an instance nobody hydrated. Collapsing
the last two would make every hand-built model with a default raise.

WHAT IS ALWAYS LOADED, AND IT IS NOT A CONVENIENCE. The primary key comes back whatever `only()`
says, because an instance without one cannot be updated, deleted or matched to its relations — a half
row with no identity is not a row.

AND THE HONEST NOTE THIS FEATURE NEEDS. For most of what people reach for `defer()` for, `select()`
is the better tool: it returns typed tuples, costs no half-built instance and cannot raise later. Use
`only()` when what you want IS the model — to hand it to code that expects one, or to write it back.
"""

from __future__ import annotations

import pytest

from snakeorm.core.exceptions import SnakeColumnNotLoaded, SnakeUnsupportedFeature
from snakeorm.dialects import SQLiteDialect
from snakeorm.drivers import SQLiteDriver
from snakeorm.fields import SnakeColumn, snake_auto, snake_int, snake_str
from snakeorm.migration import emit_create_table
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery
from snakeorm import snake_table
from snakeorm.decorators import snake_model
from snakeorm.session import SnakeSession


@snake_model(table="oad_visitas")
class _Visit(SnakeModel):
    """A volume row: a key, two columns a report wants and one it never prints."""

    id: SnakeColumn[int] = snake_auto()
    path: SnakeColumn[str] = snake_str()
    agent: SnakeColumn[str] = snake_str()
    ms: SnakeColumn[int] = snake_int()


def _session() -> SnakeSession:
    """A session over an in-memory SQLite with the one table this file needs, seeded."""
    driver = SQLiteDriver.connect(":memory:")
    dialect = SQLiteDialect()
    driver.execute(emit_create_table(snake_table(_Visit), dialect), ())
    driver.commit()
    session = SnakeSession(driver, dialect)
    session.add(_Visit(path="/a", agent="Firefox", ms=12))
    session.add(_Visit(path="/b", agent="Safari", ms=30))
    session.commit()
    return session


def test_only_brings_the_named_columns_and_the_key() -> None:
    """The named ones are there, and so is the PK whether or not it was named."""
    session = _session()

    rows = session.all(SnakeQuery(_Visit).only(_Visit.path))

    assert [row.path for row in rows] == ["/a", "/b"]
    assert [row.id for row in rows] == [1, 2]


def test_only_emits_fewer_columns() -> None:
    """The point of the feature, pinned where it happens: the SELECT is shorter."""
    sql, _ = SnakeQuery(_Visit).only(_Visit.path).to_sql(SQLiteDialect())

    assert sql.startswith('SELECT "id", "path" FROM'), sql


def test_reading_a_column_that_was_left_out_raises() -> None:
    """The cost of the feature, and the reason it is safe: a missing value is never guessed.

    Without the sentinel this returns the column's default and the caller gets a wrong answer with no
    error at all. That is the failure this whole file exists to make impossible.
    """
    session = _session()
    row = session.all(SnakeQuery(_Visit).only(_Visit.path))[0]

    with pytest.raises(SnakeColumnNotLoaded, match="agent"):
        _ = row.agent


def test_a_compound_of_narrowed_branches_hydrates_the_narrow_row() -> None:
    """A set of two narrowed branches is still a narrow row, and the session has to be told.

    THIS IS THE PATH THAT FORGOT. `map_rows` asks the query which columns it projected instead of
    counting the row's width; a compound had no answer to give, so the two values of an `only()`
    were laid against every column of the table and landed on the wrong attributes. It is the same
    failure `AsyncSession.all` had before both colours shared this code, on a different path.
    """
    session = _session()
    firefox = SnakeQuery(_Visit).filter(_Visit.agent == "Firefox").only(_Visit.path)
    safari = SnakeQuery(_Visit).filter(_Visit.agent == "Safari").only(_Visit.path)

    rows = session.all(firefox.union_all(safari).order_by(_Visit.id.asc()))

    assert [row.path for row in rows] == ["/a", "/b"]
    with pytest.raises(SnakeColumnNotLoaded, match="agent"):
        _ = rows[0].agent


def test_defer_is_the_other_half_and_leaves_the_rest_whole() -> None:
    """`defer()` names what NOT to bring; everything else arrives as usual."""
    session = _session()

    row = session.all(SnakeQuery(_Visit).defer(_Visit.agent))[0]

    assert (row.path, row.ms) == ("/a", 12)
    with pytest.raises(SnakeColumnNotLoaded, match="agent"):
        _ = row.agent


def test_a_narrowed_row_is_still_printable() -> None:
    """A `repr` must never raise, and a half row is exactly when somebody most wants to print one.

    Reading an unloaded column raises, which is the feature. `__repr__` reads every column, so it
    inherited the raise: printing the object under inspection killed the inspection.
    """
    session = _session()
    row = session.all(SnakeQuery(_Visit).only(_Visit.path))[0]

    printed = repr(row)

    assert "path='/a'" in printed
    assert "agent=<not loaded>" in printed


def test_deferring_the_key_is_refused() -> None:
    """The PK is not optional: an instance with no identity cannot be written back or matched."""
    with pytest.raises(SnakeUnsupportedFeature, match="primary key"):
        SnakeQuery(_Visit).defer(_Visit.id)


def test_an_instance_the_user_built_still_reads_its_values() -> None:
    """The sentinel must not leak into the ordinary path: a hand-built model is not a partial one."""
    fresh = _Visit(path="/c", agent="Links", ms=1)

    assert (fresh.path, fresh.agent) == ("/c", "Links")


def test_only_and_defer_do_not_combine() -> None:
    """Naming both what to bring and what to leave is two answers to one question."""
    with pytest.raises(SnakeUnsupportedFeature, match="second answer to one question"):
        SnakeQuery(_Visit).only(_Visit.path).defer(_Visit.agent)


def test_the_paths_that_do_not_project_refuse_the_knob() -> None:
    """A COUNT and an EXISTS emit no column list, so naming one is a question they cannot answer.

    `_guard_unsupported` derives the knobs from `__slots__`, so adding `_columns` guarded every path
    that does not honour it the day it appeared — which is the whole reason the guard reads the slots
    instead of a list somebody maintains.

    EXCEPT that `to_exists_sql` called no guard at all, and had not since it was written: it swallowed
    `group_by`, `having`, `distinct` and `lock` in silence. Adding a tenth knob is what surfaced it,
    and it is the same shape as entry #18 of the bug journal — a fix applied to `count()` and not to
    its brothers.
    """
    session = _session()
    narrowed = SnakeQuery(_Visit).only(_Visit.path)

    with pytest.raises(SnakeUnsupportedFeature, match=r"COUNT\(\*\) does not emit"):
        session.count(narrowed)
    with pytest.raises(SnakeUnsupportedFeature, match="SELECT EXISTS does not emit"):
        session.exists(narrowed)


def test_an_exists_over_groups_is_refused_rather_than_answered_about_rows() -> None:
    """The half of the missing guard that has nothing to do with this feature.

    An EXISTS with a `group_by` is asking whether a GROUP exists, and the emitted SQL asks about
    rows. Before the guard it answered the second question without saying so.
    """
    session = _session()

    with pytest.raises(SnakeUnsupportedFeature, match="group_by"):
        session.exists(SnakeQuery(_Visit).group_by(_Visit.path))


def test_the_refusal_advises_about_the_knob_that_was_set() -> None:
    """The message names `only()/defer()` and advises about columns, not about locking.

    The guard takes ONE remedy per emitter, which is right until two knobs are dropped at once: the
    first `only().include()` said "does not emit only()/defer() ... lock the rows in a separate
    query", which is advice about something nobody had touched. So a knob may now carry its own
    remedy, and the path's is appended only when some dropped knob has none.

    In an ORM whose doctrine is that the message IS the product, a refusal that answers a question
    nobody asked is the same defect as a wrong result, one layer up.
    """
    session = _session()

    with pytest.raises(SnakeUnsupportedFeature) as raised:
        session.count(SnakeQuery(_Visit).only(_Visit.path))

    message = str(raised.value)
    assert "only()/defer()" in message
    assert "Ask for the columns with select(...)" in message
    # The COUNT's own remedy is about groups and distinct rows, and nobody asked about those. It is
    # appended only when a dropped knob has no remedy of its own.
    assert "number of groups" not in message


def test_streaming_a_narrowed_query_hydrates_the_narrow_row() -> None:
    """`iterate()` over an `only()` gives half rows, not a crash — and it used to be the crash.

    THE TWO READS HAD DRIFTED, and the shape of the drift is the reason this test is worth its
    lines. `all()` asks the query which columns it projected and slices the hydration plan to match;
    the streaming path asked nothing and hydrated against the FULL plan, so a four-column table read
    with three columns blew up inside the generator with `zip() argument 2 is shorter than argument
    1` — an error from the mapper, naming neither `only()` nor `iterate()`.

    The SQL was already right: `to_sql` emits the narrowed SELECT on both paths, because it is the
    same method. What differed was what happened to the row afterwards, which is the worst place for
    two paths to disagree — everything up to the row is shared, so nothing about the query looks
    suspicious.

    And it is exactly the combination a volume table wants: streaming keeps the row COUNT out of
    memory and `only()` keeps the row WIDTH off the wire, and neither one does the other's job.
    """
    session = _session()

    rows = list(session.iterate(SnakeQuery(_Visit).only(_Visit.path)))

    assert [row.path for row in rows] == ["/a", "/b"]
    assert [row.id for row in rows] == [1, 2]
    with pytest.raises(SnakeColumnNotLoaded, match="was not loaded"):
        rows[0].agent


def test_streaming_a_deferred_query_leaves_the_deferred_column_unloaded() -> None:
    """The `defer()` half of the same path: everything but the wide column, and it still raises."""
    session = _session()

    rows = list(session.iterate(SnakeQuery(_Visit).defer(_Visit.agent)))

    assert [(row.path, row.ms) for row in rows] == [("/a", 12), ("/b", 30)]
    with pytest.raises(SnakeColumnNotLoaded, match="was not loaded"):
        rows[0].agent


def test_the_asynchronous_stream_narrows_the_same_way() -> None:
    """The same fix on the other side of the colour line, which is where it would have been forgotten.

    The two `_stream` bodies are two copies of one decision — `await` is syntax and one function
    cannot serve both colours — so a narrowing added to one of them and not the other is a demo that
    works on two frameworks and raises on the third. That is the whole reason this repository asserts
    parity instead of trusting it.
    """
    import asyncio

    from snakeorm.drivers import AsyncSQLiteDriver
    from snakeorm.session import AsyncSession

    async def work() -> list[str]:
        driver = await AsyncSQLiteDriver.connect(":memory:")
        dialect = SQLiteDialect()
        await driver.execute(emit_create_table(snake_table(_Visit), dialect), ())
        await driver.commit()
        session = AsyncSession(driver, dialect)
        await session.add(_Visit(path="/a", agent="Firefox", ms=12))
        await session.commit()
        try:
            return [
                row.path
                async for row in session.iterate(SnakeQuery(_Visit).only(_Visit.path))
            ]
        finally:
            await session.close()

    assert asyncio.run(work()) == ["/a"]


def test_the_asynchronous_all_narrows_the_same_way() -> None:
    """`await session.all(query.only(...))` gives half rows, and it used to raise from the mapper.

    THE ASYMMETRY WAS INVISIBLE FROM EITHER SIDE ALONE. `SnakeSession.all` maps its rows through a
    helper that asks the query what it projected; `AsyncSession.all` inlined the full-row hydration
    in three places instead, so the feature worked on two demos and raised on the third — with a
    `zip()` of unequal lengths that names neither `only()` nor the session.

    That is the same defect as the streaming one above and it is worth two tests rather than one:
    they are two read paths, and the day somebody narrows one of them by hand the other is exactly
    where the fix will not have gone.
    """
    import asyncio

    from snakeorm.drivers import AsyncSQLiteDriver
    from snakeorm.session import AsyncSession

    async def work() -> tuple[list[str], object]:
        driver = await AsyncSQLiteDriver.connect(":memory:")
        dialect = SQLiteDialect()
        await driver.execute(emit_create_table(snake_table(_Visit), dialect), ())
        await driver.commit()
        session = AsyncSession(driver, dialect)
        await session.add(_Visit(path="/a", agent="Firefox", ms=12))
        await session.commit()
        try:
            rows = await session.all(SnakeQuery(_Visit).only(_Visit.path))
            return [row.path for row in rows], rows[0]
        finally:
            await session.close()

    routes, first = asyncio.run(work())

    assert routes == ["/a"]
    with pytest.raises(SnakeColumnNotLoaded, match="was not loaded"):
        first.agent  # type: ignore[attr-defined]
