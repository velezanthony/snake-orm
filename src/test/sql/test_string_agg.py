"""Joining a group's values into one string: `string_agg(Tag.name, ", ")`.

THE AGGREGATE THAT SENT PEOPLE BACK TO PYTHON. Everything else a report needs — counting, adding,
the largest — the ORM already did in the engine. Listing the tags of a post did not exist, so the
answer was to fetch every row and `", ".join(...)` them, which is the N+1 shape this ORM spends its
whole design avoiding: rows crossing the wire to be collapsed by the client.

THREE SPELLINGS, AND THE SEPARATOR DOES NOT TRAVEL THE SAME WAY IN THEM. Measured:

    PostgreSQL   STRING_AGG("name", $1 ORDER BY "name")          separator is an ARGUMENT
    SQLite       group_concat("name", ? ORDER BY "name")         separator is an ARGUMENT
    MySQL        GROUP_CONCAT(`name` ORDER BY `name` SEPARATOR ', ')   separator is SYNTAX

MariaDB rejects a placeholder after `SEPARATOR` outright:

    ERROR 1064 (42000): ... near '?) AS c'

So on two engines the separator is a parameter and on the third it cannot be. That is not papered
over by interpolating everywhere: each dialect does what its engine allows, and MySQL escapes the
string through the same `literal()` the DDL defaults already use. The tests below pin the parameter
count precisely, because "it works on my engine" is exactly how this class of bug survives.

ORDERING IS PORTABLE, which was worth checking rather than assuming — SQLite only grew
`ORDER BY` inside `group_concat` in 3.44. Without it the concatenation comes back in whatever order
the engine felt like, which for a value somebody reads is a different answer every run.
"""

from __future__ import annotations

from snakeorm import (
    SnakeColumn,
    SnakeQuery,
    SnakeSession,
    SQLiteDriver,
    snake_auto,
    snake_column,
    snake_model,
    snake_table,
)
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.expressions import string_agg
from snakeorm.migration import emit_create_table
from snakeorm.model import SnakeModel
from snakeorm.sql.value import emit_value


@snake_model(table="stragg_tags")
class _Tag(SnakeModel):
    """Tags belonging to a post: the shape every "list them in one cell" report has."""

    id: SnakeColumn[int] = snake_auto()
    post_id: SnakeColumn[int] = snake_column()
    name: SnakeColumn[str] = snake_column()


def test_postgres_takes_the_separator_as_an_argument() -> None:
    """`STRING_AGG(col, %s ORDER BY ...)`: the separator is a normal argument, so it parameterises."""
    params: list[object] = []
    sql = emit_value(
        string_agg(_Tag.name, ", ", order_by=[_Tag.name.asc()]),
        PostgresDialect(),
        params,
        None,
    )
    assert sql == 'STRING_AGG("name", %s ORDER BY "name" ASC)'
    assert params == [", "]


def test_sqlite_spells_it_group_concat_and_also_parameterises() -> None:
    """A different NAME and the same shape: the separator is still an argument here."""
    params: list[object] = []
    sql = emit_value(
        string_agg(_Tag.name, ", ", order_by=[_Tag.name.asc()]),
        SQLiteDialect(),
        params,
        None,
    )
    assert sql == 'group_concat("name", ? ORDER BY "name" ASC)'
    assert params == [", "]


def test_mysql_makes_the_separator_syntax_so_it_cannot_be_a_parameter() -> None:
    """`SEPARATOR` is a KEYWORD in MySQL, and it was measured to reject a placeholder after it.

    So the string is escaped through the dialect's own `literal()`, the one the DDL defaults use.
    The empty `params` is the whole point of the assertion: this engine takes a different route.
    """
    params: list[object] = []
    sql = emit_value(
        string_agg(_Tag.name, ", ", order_by=[_Tag.name.asc()]),
        MySQLDialect(),
        params,
        None,
    )
    assert sql == "GROUP_CONCAT(`name` ORDER BY `name` ASC SEPARATOR ', ')"
    assert params == []


def test_a_quote_in_the_separator_is_escaped_and_does_not_close_the_string() -> None:
    """The separator reaches MySQL's statement, so the injection question has to have an answer.

    It does, and it is the existing one: `literal()` doubles the quote and escapes the backslash,
    which is what it already does for every DDL default in the ORM.
    """
    sql = emit_value(string_agg(_Tag.name, "' OR 1=1 --"), MySQLDialect(), [], None)
    assert "'' OR 1=1 --'" in sql
    assert sql.count("'") % 2 == 0


def test_without_an_order_the_clause_is_simply_absent() -> None:
    """Not every caller needs a stable order; the ones that do ask for it and get it."""
    for dialect, expected in (
        (PostgresDialect(), 'STRING_AGG("name", %s)'),
        (SQLiteDialect(), 'group_concat("name", ?)'),
        (MySQLDialect(), "GROUP_CONCAT(`name` SEPARATOR ', ')"),
    ):
        assert emit_value(string_agg(_Tag.name, ", "), dialect, [], None) == expected


def test_it_carries_the_paths_of_its_argument_and_of_its_order() -> None:
    """Both plan JOINs: aggregating one column while ordering by another is a normal thing to want."""
    node = string_agg(_Tag.name, ", ", order_by=[_Tag.post_id.asc()])
    assert set(node.paths()) == {("name",), ("post_id",)}


def test_the_engine_joins_the_group_in_the_order_that_was_asked_for() -> None:
    """Emission is half of it. Inserted out of order on purpose: unordered would come back 'c,a,b'."""
    dialect = SQLiteDialect()
    driver = SQLiteDriver.connect(":memory:")
    driver.execute(emit_create_table(snake_table(_Tag), dialect), ())
    driver.commit()
    session = SnakeSession(driver, dialect)
    for name in ("c", "a", "b"):
        session.add(_Tag(post_id=1, name=name))
    session.add(_Tag(post_id=2, name="z"))
    session.commit()

    rows = session.select(
        SnakeQuery(_Tag).group_by(_Tag.post_id).order_by(_Tag.post_id.asc()),
        _Tag.post_id,
        string_agg(_Tag.name, "-", order_by=[_Tag.name.asc()]),
    )
    assert rows == [(1, "a-b-c"), (2, "z")]


def test_the_group_can_be_ordered_by_more_than_one_key() -> None:
    """A tie-break is TWO keys, and two keys are a comma-separated list inside the call.

    Ordering by one column leaves every tie to the engine, which is the same "a different answer
    every run" this module's ordering exists to close — only narrower. Run together without the
    comma the clause is not a coarser order, it is a column name that does not exist.
    """
    params: list[object] = []
    sql = emit_value(
        string_agg(_Tag.name, ", ", order_by=[_Tag.post_id.asc(), _Tag.name.desc()]),
        PostgresDialect(),
        params,
        None,
    )

    assert sql == 'STRING_AGG("name", %s ORDER BY "post_id" ASC, "name" DESC)'
