"""`add_all` must not let the FIRST instance answer for the rest of the batch.

`add_all` computed the values for all N instances and then branched on `if not rows[0]` — the first
one alone. Inside that branch it emitted `INSERT ... DEFAULT VALUES` for EVERY instance, and
`rows[1..n]` were computed and dropped on the floor.

So a batch whose first element carries no client values silently stored the defaults for all of
them. Turn the same list round and it raises `SnakeEmitError` instead, from the guard that already
exists for rows with different columns. **The POSITION of an element decided between a loud error
and a silent loss of data**, which is the worst shape a failure can take.

The bug was written in the gap between a comment and its code: the comment describes a MODEL ("a
model with only an autoincrementing PK"), the `if` asks about an INSTANCE. Those are the same thing
only when every instance of the model has the same shape — which is exactly what nothing checked.

The guard is the second half of a requirement that was already three lines above: `add_all` already
demanded a single MODEL. Once the shapes match too, `rows[0]` answers for all of them by
construction and the branch becomes correct rather than lucky.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.decorators import snake_model
from snakeorm.dialects import SQLiteDialect
from snakeorm.fields import SnakeColumn, snake_auto, snake_int, snake_str
from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.session import SnakeSession


@snake_model(table="aa_notes")
class _Note(SnakeModel):
    """A model whose `text` has a SERVER default, so it stays out of `__init__`."""

    id: SnakeColumn[int] = snake_auto()
    text: SnakeColumn[str] = snake_str(server_default_sql="'untitled'")


@snake_model(table="aa_plain")
class _Plain(SnakeModel):
    """The control: every column is client-side, so every instance has the same shape."""

    id: SnakeColumn[int] = snake_auto()
    n: SnakeColumn[int] = snake_int()


snake_link()


class _FakeDriver:
    """Fake driver: it records the statements it was asked to run (no database)."""

    def __init__(self, width: int = 2) -> None:
        self.calls: list[tuple[str, Sequence[object]]] = []
        # RETURNING lists every column, so a row has to be as wide as the table or the session's
        # `strict=True` zip refuses it. SQLite DOES have RETURNING, which is what makes this path
        # the one under test rather than a detail of the double.
        self._width = width

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.calls.append((sql, params))
        rows = max(1, sql.count("RETURNING") and sql.count("),") + 1)
        return [tuple(1 for _ in range(self._width)) for _ in range(rows)]

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        self.calls.append((sql, params))
        return 1

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def savepoint(self, name: str) -> None: ...
    def release_savepoint(self, name: str) -> None: ...
    def rollback_to_savepoint(self, name: str) -> None: ...
    def close(self) -> None: ...


def _session() -> tuple[SnakeSession, _FakeDriver]:
    """A session over the fake driver. SQLite, whose dialect DOES have RETURNING — which is why the
    double has to return rows as wide as the table."""
    driver = _FakeDriver()
    return SnakeSession(driver, SQLiteDialect()), driver


def test_a_batch_whose_first_row_is_empty_does_not_swallow_the_others() -> None:
    """THE bug: the values of b and c reached the database, or nothing was written at all.

    Before the guard this stored `('untitled', 'untitled', 'untitled')` without a word. The
    assertion is deliberately on the REFUSAL and not on the emitted SQL: three rows written wrong
    and a refusal are both "did not lose the data" only if you squint, and this run must be able to
    tell them apart.
    """
    session, _ = _session()
    first, second = _Note(), _Note()
    second.text = "hello"

    with pytest.raises(SnakeEmitError, match="same columns"):
        session.add_all([first, second])


def test_the_same_batch_the_other_way_round_says_the_same_thing() -> None:
    """The symmetry is the whole point: order must not change the answer.

    Reversed, this list already raised — the emitter refuses rows with different columns. The two
    orders reaching two different outcomes is what made the defect so hard to see: whoever hit the
    error assumed the ORM had it covered.
    """
    session, _ = _session()
    first, second = _Note(), _Note()
    first.text = "hello"

    with pytest.raises(SnakeEmitError, match="same columns"):
        session.add_all([first, second])


def test_a_batch_that_is_uniformly_empty_still_uses_the_default_values_path() -> None:
    """The legitimate case the guard must NOT eat: nobody set anything, so DEFAULT VALUES is right.

    Without this the fix would be "refuse mixed batches" plus "refuse the batch that motivated the
    branch in the first place", and a model whose columns all have server defaults could not be
    bulk-inserted at all.
    """
    session, driver = _session()

    session.add_all([_Note(), _Note(), _Note()])

    statements = [sql for sql, _ in driver.calls]
    assert len(statements) == 3, "one INSERT per instance, as `add` does"
    assert all("DEFAULT VALUES" in sql for sql in statements)


def test_a_uniform_batch_with_values_is_still_one_multi_row_insert() -> None:
    """The other floor: the ordinary batch keeps being ONE statement, not N.

    This is what makes `add_all` worth having over a loop of `add`, and a guard that forced the
    per-instance path would have thrown it away while every other test here stayed green.
    """
    session, driver = _session()

    session.add_all([_Plain(n=1), _Plain(n=2), _Plain(n=3)])

    assert len(driver.calls) == 1, "the batch was split: add_all stopped batching"
    sql, params = driver.calls[0]
    assert sql.count("(?)") == 3 or sql.count("?") == 3
    assert list(params) == [1, 2, 3]
