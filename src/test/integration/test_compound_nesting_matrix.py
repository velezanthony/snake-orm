"""Nested set operations EXECUTED on the THREE engines, comparing the ROWS they answer.

The type says a branch of a compound may itself be a compound (`SnakeCompoundBranch` includes
`SnakeCompound`), so `a.union(b.except_(c))` is legal and nothing in the suite had ever run one.
This file runs the whole 4x4 operator matrix, nested to the left and to the right, and asks the only
question worth asking of a set operation: do the three engines return the SAME rows?

They did not. Postgres and MySQL parenthesise the branches; SQLite refuses parentheses there, so the
inner grouping vanished from the text and the engine read the operators left to right — a DIFFERENT
set, compiled, executed and hydrated with no error anywhere. `except_(union)` came back empty on
Postgres and with two rows on SQLite.

Emission could not have caught it: every one of those strings is valid SQL. Only running the same
Python against the three engines and comparing rows can.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest

from test.conftest import NO_MYSQL_REASON, NO_SERVER_REASON

from snakeorm import (
    MySQLDialect,
    PostgresDialect,
    PsycopgDriver,
    PyMySQLDriver,
    SQLiteDialect,
    SQLiteDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SnakeToOne,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
    snake_to_one,
)
from snakeorm.core.exceptions import SnakeEmitError
from snakeorm.dialects import SnakeDialect
from snakeorm.drivers.base import SnakeDriver
from snakeorm.migration import emit_create_table
from snakeorm.query.compound import SnakeCompound, SnakeCompoundBranch
from snakeorm.registry import registry
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="nest_orders")
class Order(SnakeModel):
    """Orders whose two criteria OVERLAP, so a regrouping changes which rows come back."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    status: SnakeColumn[str] = snake_str(max_length=20)
    amount: SnakeColumn[int] = snake_int()


@snake_model(table="nest_cats")
class Cat(SnakeModel):
    """A self-referential hierarchy, so a recursion can be used as a branch of a set."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str(max_length=20)
    parent_id: SnakeColumn[int | None] = snake_int()
    parent: SnakeToOne["Cat | None"] = snake_to_one(parent_id)


snake_link()

REFUSED = "refused"
"""What an engine answers when it will not express the query. It is not a wrong answer."""

_ORDERS = ((1, "open", 100), (2, "open", 900), (3, "closed", 900), (4, "closed", 100))
_CATS = ((1, "root", None), (2, "child", 1), (3, "gchild", 2), (4, "other", None))
_OPERATORS = ("union", "union_all", "except_", "intersect")


def _seed(session: SnakeSession) -> None:
    """Four orders and a two-branch hierarchy, with a different value per column.

    Distinct values per column on purpose: a projection lined up wrong has to be VISIBLE, and rows
    of zeros hide exactly that.
    """
    session.add_all([Order(id=i, status=s, amount=a) for i, s, a in _ORDERS])
    session.commit()
    session.add_all([Cat(id=i, name=n, parent_id=p) for i, n, p in _CATS])
    session.commit()


def _build(
    driver: SnakeDriver, dialect: SnakeDialect, drop: str | None
) -> SnakeSession:
    """Creates both tables on this engine and fills them."""
    for model in (Order, Cat):
        table = registry.table_of(model)
        assert table is not None
        if drop is not None:
            driver.execute(drop % table.name, ())
        driver.execute(emit_create_table(table, dialect), ())
    driver.commit()
    session = SnakeSession(driver, dialect)
    _seed(session)
    return session


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The THREE engines at once: the comparison is the test, so one missing is a skip.

    A cross-engine agreement checked over two engines is a weaker statement than it looks, and the
    engine left out is always the one nobody set a gate for.
    """
    import psycopg2
    import pymysql

    sqlite_driver = SQLiteDriver.connect(":memory:")
    try:
        postgres_driver = PsycopgDriver.connect(dsn())
    except psycopg2.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_SERVER_REASON}: {error}")
    host = os.environ.get("MYSQL_HOST")
    if not host:  # pragma: no cover - environment
        pytest.skip(f"{NO_MYSQL_REASON}: MYSQL_HOST is not set")
    try:
        mysql_driver = PyMySQLDriver.connect(
            host=host,
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ.get("MYSQL_DB", "snakeorm_db"),
        )
    except pymysql.err.OperationalError as error:  # pragma: no cover - environment
        pytest.skip(f"{NO_MYSQL_REASON}: {error}")

    built = {
        "sqlite": _build(sqlite_driver, SQLiteDialect(), None),
        "postgres": _build(
            postgres_driver, PostgresDialect(), "DROP TABLE IF EXISTS %s CASCADE"
        ),
        "mysql": _build(mysql_driver, MySQLDialect(), "DROP TABLE IF EXISTS %s"),
    }
    try:
        yield built
    finally:
        for driver, drop in (
            (postgres_driver, "DROP TABLE IF EXISTS %s CASCADE"),
            (mysql_driver, "DROP TABLE IF EXISTS %s"),
        ):
            for name in ("nest_orders", "nest_cats"):
                driver.execute(drop % name, ())
            driver.commit()
            driver.close()
        sqlite_driver.close()


def _open() -> SnakeQuery[Order]:
    """Orders 1 and 2."""
    return SnakeQuery(Order).filter(Order.status == "open")


def _large() -> SnakeQuery[Order]:
    """Orders 2 and 3."""
    return SnakeQuery(Order).filter(Order.amount > 500)


def _cheap() -> SnakeQuery[Order]:
    """Orders 1 and 4."""
    return SnakeQuery(Order).filter(Order.amount < 500)


def _answers(
    engines: dict[str, SnakeSession], build: Callable[[], SnakeCompoundBranch[Order]]
) -> dict[str, list[int] | str]:
    """What each engine answers: the ids it returns, or `REFUSED` if it will not express it."""
    answers: dict[str, list[int] | str] = {}
    for name, session in engines.items():
        try:
            answers[name] = sorted(row.id for row in session.all(build()))
        except SnakeEmitError:
            answers[name] = REFUSED
    return answers


def _agree(answers: dict[str, list[int] | str]) -> bool:
    """Do the engines that DID answer all say the same thing? A refusal abstains."""
    given = [rows for rows in answers.values() if rows != REFUSED]
    return all(rows == given[0] for rows in given)


@pytest.mark.parametrize("inner", _OPERATORS)
@pytest.mark.parametrize("outer", _OPERATORS)
def test_left_nesting_gives_the_same_rows_on_the_three_engines(
    inner: str, outer: str, engines: dict[str, SnakeSession]
) -> None:
    """`(a INNER b) OUTER c` means the same on the three engines, and always did.

    Chaining to the left is what the bare text already says: SQL reads the operators left to right,
    so the grouping survives losing the parentheses. All sixteen pairs agree, which is why the fix
    for the right-hand case may not touch this one — it is the ordinary chain.
    """
    answers = _answers(
        engines,
        lambda: getattr(getattr(_open(), inner)(_large()), outer)(_cheap()),
    )

    assert REFUSED not in answers.values(), "left chaining is expressible everywhere"
    assert _agree(answers), f"({inner}) {outer} disagrees across engines: {answers}"


@pytest.mark.parametrize("inner", _OPERATORS)
@pytest.mark.parametrize("outer", _OPERATORS)
def test_right_nesting_never_answers_two_different_sets(
    inner: str, outer: str, engines: dict[str, SnakeSession]
) -> None:
    """`a OUTER (b INNER c)` either means the same everywhere, or is REFUSED where it cannot.

    This is the bug. Twelve of these sixteen pairs used to answer one set on Postgres and MySQL and
    a different one on SQLite, silently: the inner parentheses were dropped and the engine regrouped
    left to right. What must never happen is two engines answering two different sets.
    """
    answers = _answers(
        engines,
        lambda: getattr(_open(), outer)(getattr(_large(), inner)(_cheap())),
    )

    assert _agree(answers), f"{outer} ({inner}) disagrees across engines: {answers}"


def test_the_engine_that_cannot_group_a_branch_refuses_instead_of_regrouping(
    engines: dict[str, SnakeSession],
) -> None:
    """The refusal is NAMED, so the agreement above cannot be met by everybody staying silent.

    `open EXCEPT (large UNION cheap)` is empty by construction: every open order is either large or
    cheap. SQLite answered two rows. Now it refuses, and the other two still answer nothing.
    """
    answers = _answers(engines, lambda: _open().except_(_large().union(_cheap())))

    assert answers["sqlite"] == REFUSED
    assert answers["postgres"] == [] and answers["mysql"] == []


def test_a_recursive_branch_runs_or_is_refused_but_never_blows_up_in_the_driver(
    engines: dict[str, SnakeSession],
) -> None:
    """A `WITH RECURSIVE` as a branch of a set is Postgres-only, and the other two must say so.

    The type advertises `SnakeRecursive` as a legal branch and the docstring backed it with a check
    against Postgres alone. SQLite answered `near "WITH": syntax error` and MySQL error 1064 — the
    driver complaining about SQL the user never wrote.
    """

    def built() -> SnakeCompound[Cat]:
        return (
            SnakeQuery(Cat)
            .filter(Cat.name == "other")
            .union(
                SnakeQuery(Cat)
                .filter(Cat.id == 1)
                .recursive(on=(Cat.parent_id, Cat.id))
            )
        )

    answers: dict[str, list[int] | str] = {}
    for name, session in engines.items():
        try:
            answers[name] = sorted(row.id for row in session.all(built()))
        except SnakeEmitError:
            answers[name] = REFUSED

    assert answers["postgres"] == [1, 2, 3, 4]
    assert answers["sqlite"] == REFUSED and answers["mysql"] == REFUSED
