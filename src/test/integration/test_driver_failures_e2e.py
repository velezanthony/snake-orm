"""One violated constraint, three engines, ONE exception to catch.

The ORM's promise is that a model written once runs on the three. It did not cover what happens
when a write is REFUSED: a duplicate key came back as `psycopg2.errors.UniqueViolation`, as
`pymysql.err.IntegrityError` and as `sqlite3.IntegrityError` — three types for one condition, so the
`except` that handled it was the one part of an application that could not be ported.

CLASSIFIED BY CODE AND NEVER BY MESSAGE. Reading the text is how a detector fails open, which this
repository has already paid for once, and it is not needed: all three engines say exactly which
constraint broke. Postgres in the SQLSTATE (`23505`), MySQL in its errno (`1062` — its SQLSTATE is
`23000` for all four and says nothing), SQLite in `sqlite_errorname`
(`SQLITE_CONSTRAINT_UNIQUE`, available since Python 3.11, which is this project's floor).

And never by the driver's CLASS either, which is the trap this file exists to keep shut: on MySQL a
CHECK violation arrives as `OperationalError` while the other three arrive as `IntegrityError`.
Keyed on the class, that one lands in the wrong bucket on one engine only.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeSession,
    SnakeToOne,
    snake_int,
    snake_link,
    snake_table,
    snake_model,
    snake_str,
    snake_to_one,
)
from snakeorm.core.exceptions import (
    SnakeCheckViolation,
    SnakeForeignKeyViolation,
    SnakeIntegrityError,
    SnakeNotNullViolation,
    SnakeUniqueViolation,
)
from snakeorm.drivers.base import SnakeDriver
from snakeorm.fields import snake_check, snake_checks
from snakeorm.migration.ddl import emit_add_foreign_key
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@snake_model(table="fx_parents")
class Parent(SnakeModel):
    """The row a child points at, with a unique column to collide on."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    code: SnakeColumn[str] = snake_str(max_length=10, unique=True)


@snake_model(table="fx_children")
class Child(SnakeModel):
    """A foreign key, a NOT NULL and a CHECK: one row type for three of the four conditions."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    parent_id: SnakeColumn[int] = snake_int()
    parent: SnakeToOne[Parent] = snake_to_one(parent_id)
    qty: SnakeColumn[int] = snake_int()


snake_checks(Child, snake_check(Child.qty > 0, name="ck_fx_children_qty_positive"))
snake_link()


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with one parent seeded, so a child has something valid to point at.

    The driver is captured through `three_sessions`'s own `wrap` hook rather than reached for
    privately: the foreign key has to be added by hand, and there is no public way to run a DDL
    statement through a session — `raw()` is for SELECTs and asks for the row type to map into.

    WHY BY HAND AT ALL. `create_tables` emits the CREATE and nothing else, so on the two engines
    that want a foreign key in an ALTER of its own the constraint is simply absent, and an INSERT
    that ought to be refused succeeds. SQLite carries it inline and cannot ADD CONSTRAINT — it says
    so in the catalogue — so it is ASKED before being told.
    """
    drivers: dict[str, SnakeDriver] = {}

    def capture(engine: str, driver: SnakeDriver) -> SnakeDriver:
        drivers[engine] = driver
        return driver

    with three_sessions([Parent, Child], wrap=capture) as sessions:
        for engine, session in sessions.items():
            if session.dialect.supports_add_constraint:
                drivers[engine].execute(
                    emit_add_foreign_key(
                        snake_table(Child),
                        snake_table(Child).relationships[0],
                        snake_table(Parent),
                        session.dialect,
                    ),
                    (),
                )
            session.add(Parent(id=1, code="A"))
            session.commit()
        yield sessions
        # A refused write leaves Postgres's transaction aborted, and every later statement — the
        # teardown's DROP included — answers `InFailedSqlTransaction`. Rolling back here rather than
        # in each test keeps the tests about the exception they are asserting.
        for session in sessions.values():
            session.rollback()


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_duplicate_key_is_one_exception_on_the_three(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The case an application actually branches on: "that one already exists"."""
    session = engines[engine]

    with pytest.raises(SnakeUniqueViolation, match="UNIQUE constraint"):
        session.add(Parent(id=2, code="A"))
        session.commit()


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_missing_parent_is_one_exception_on_the_three(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """A foreign key pointing nowhere. SQLite only enforces it with `PRAGMA foreign_keys=ON`."""
    session = engines[engine]

    with pytest.raises(SnakeForeignKeyViolation, match="FOREIGN KEY"):
        session.add(Child(id=1, parent_id=999, qty=5))
        session.commit()


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_broken_check_is_one_exception_on_the_three(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The one that proves the classification is by CODE: MySQL raises `OperationalError` here."""
    session = engines[engine]

    with pytest.raises(SnakeCheckViolation, match="CHECK constraint"):
        session.add(Child(id=2, parent_id=1, qty=-1))
        session.commit()


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_driver_exception_is_not_thrown_away(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Chained, not masked: `__cause__` keeps the original, and the traceback prints both.

    That is the difference between wrapping and hiding. Whoever catches gets a portable name;
    whoever debugs still gets psycopg2's or pymysql's own words about what the server said.
    """
    session = engines[engine]

    with pytest.raises(SnakeIntegrityError, match="constraint") as caught:
        session.add(Parent(id=3, code="A"))
        session.commit()

    assert caught.value.__cause__ is not None, "the driver's exception was dropped"
    assert not isinstance(caught.value.__cause__, SnakeIntegrityError)


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_subtype_is_still_the_family(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """`except SnakeIntegrityError` catches all four, so an application can be as coarse as it likes."""
    session = engines[engine]

    with pytest.raises(SnakeIntegrityError, match="constraint"):
        session.add(Parent(id=4, code="A"))
        session.commit()


def test_not_null_is_refused_before_it_reaches_the_engine() -> None:
    """Deliberately not an engine test, and saying why matters more than the assertion.

    A `SnakeColumn[int]` is not nullable, so the ORM's own typing stops a `None` long before any
    driver sees it — `SnakeNotNullViolation` exists for the row that gets there another way (a
    column added by a migration, raw SQL, a default the server refuses). Asserting it through the
    ORM would mean writing a model that lies about its own type.
    """
    assert issubclass(SnakeNotNullViolation, SnakeIntegrityError)
