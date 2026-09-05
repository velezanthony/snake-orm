"""INTEGRATION: a CHECK declared on the model does its job on the THREE engines.

This is where the circle closes end to end: `snake_check(...)` gets declared on the class, the
compiler puts it in the graph, the DDL emits it and the DATABASE rejects the bad row. Without this
test a CHECK could compile, migrate and validate nothing, which is exactly the kind of silent
failure this project has already swallowed twice (indexes never diffed, uniqueness under two names).

Running the three is not padding here. **MySQL parsed `CHECK` and IGNORED it until 8.0.16**: the
DDL was accepted, the constraint appeared to exist and nothing was ever enforced. A rule that
validates nothing while looking installed is precisely the silent failure the paragraph above is
about, and one engine cannot answer for it.

The rejection is named per engine because THE ORM DOES NOT NORMALISE DRIVER ERRORS: a
`CheckViolation`, an `OperationalError` and an `IntegrityError` are three different classes for one
event, and the user catching them writes the same table this test does. That is a gap worth seeing
written down rather than hidden behind an `except Exception`.

Skipped gracefully when an engine is not reachable.
"""

from __future__ import annotations

from collections.abc import Iterator

from snakeorm.core.exceptions import SnakeCheckViolation
import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeRow,
    SnakeSession,
    snake_check,
    snake_checks,
    snake_int,
    snake_model,
    snake_row,
    snake_str,
    snake_table,
)
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration


@snake_model(table="ck_people")
class Person(SnakeModel):
    """A person with two domain rules enforced by the database."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    age: SnakeColumn[int] = snake_int()
    name: SnakeColumn[str] = snake_str(max_length=50)


# Outside the class body on purpose: in there, `age` is the raw descriptor and does not yet know
# its own name (`__set_name__` has not run). Out here `Person.age` is already a TYPED expression.
snake_checks(
    Person,
    snake_check(Person.age >= 18, name="ck_people_adult"),
    snake_check(Person.name != "", name="ck_people_named"),
)


@snake_row
class ConstraintName(SnakeRow):
    """The declared shape of the catalogue read: one column, one name."""

    conname: str


_ENGINES = ["postgres", "mysql", "sqlite"]


def _violation(engine: str) -> type[Exception]:
    """What the ORM raises when the engine refuses the row. One class, on the three.

    This used to be a three-branch table —`psycopg2.errors.CheckViolation`,
    `pymysql.err.OperationalError`, `sqlite3.IntegrityError`— and its docstring said "the ORM does
    not translate them, so this table is exactly what a user writes too". It does now, so the table
    collapsed to this. The parameter stays because the test is still asked of each engine: what went
    away is the idea that the ANSWER depends on which one.

    Note which class MySQL used to need. A CHECK arrives there as `OperationalError` and the other
    three constraints as `IntegrityError`, which is why the translation keys on the engine's code
    and never on the driver's class.
    """
    return SnakeCheckViolation


@pytest.fixture
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with the table created by the DDL the ORM itself generates."""
    with three_sessions([Person]) as sessions:
        yield sessions


def test_the_checks_reach_the_catalogue(engines: dict[str, SnakeSession]) -> None:
    """That BOTH constraints exist on the table, asked of Postgres's own catalogue.

    Postgres only: `pg_constraint` is its table, and the three catalogues share neither name nor
    shape. What the other two answer for is the BEHAVIOUR, below — which is the half that matters,
    and the half MySQL used to get wrong while its catalogue said everything was fine.
    """
    rows = engines["postgres"].raw(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = 'ck_people'::regclass AND contype = 'c' ORDER BY conname",
        into=ConstraintName,
    )

    assert [row.conname for row in rows] == ["ck_people_adult", "ck_people_named"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_valid_row_is_accepted(engine: str, engines: dict[str, SnakeSession]) -> None:
    """A row honouring the rules goes in without trouble, on every engine."""
    session = engines[engine]

    session.add(Person(id=1, age=30, name="Ana"))
    session.commit()

    assert session.count(SnakeQuery(Person)) == 1


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_database_rejects_a_row_breaking_the_check(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The DB rejects the underage row. The rule lives in the ENGINE, not in Python.

    This is the assertion MySQL would have failed before 8.0.16 while its catalogue listed the
    constraint happily.
    """
    session = engines[engine]

    with pytest.raises(_violation(engine)):
        session.add(Person(id=2, age=12, name="Iker"))
        session.commit()
    session.rollback()

    assert session.count(SnakeQuery(Person)) == 0


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_second_check_is_independent(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The second rule is enforced too, and separately: this row breaks only that one."""
    session = engines[engine]

    with pytest.raises(_violation(engine)):
        session.add(Person(id=3, age=40, name=""))
        session.commit()
    session.rollback()

    assert session.count(SnakeQuery(Person)) == 0


def test_the_condition_is_type_checked_at_declaration() -> None:
    """Checks the rule was compiled into the graph (so the checker did see it as a condition)."""
    table = snake_table(Person)
    assert {check.resolved_name(table.name) for check in table.checks} == {
        "ck_people_adult",
        "ck_people_named",
    }
