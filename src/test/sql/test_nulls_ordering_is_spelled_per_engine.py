"""`nulls_last()` reaches every engine, spelled the way each one understands.

`emit_order_key` concatenated `f" NULLS {key.nulls.value}"` with nobody asked. Measured against both
engines this dialect serves:

    MariaDB 11.8.8   ERROR 1064 near 'NULLS LAST'
    MySQL   8.4.11   ERROR 1064 near 'NULLS LAST'

They agree, which is the question that had to be settled before touching anything: `mysql.py`
serves two engines and exists partly because it "cannot promise what only one of them does". A
throwaway MySQL 8 container answered it; measuring on MariaDB and calling it MySQL is the mistake
that file was written to avoid.

And `.order_by(User.nickname.asc().nulls_last())` is the verbatim example in
`docs/users/getting-started/querying.md`, so this was published API emitting raw syntax that one of
the three first-class engines refuses.

IT IS A SHAPE DIFFERENCE, NOT A CAPABILITY. All three engines order nulls; what changes is the
spelling. That is precisely the reasoning `Cap.ILIKE` carries in the catalogue — "Declared `Nope`
here, it said the engine could not do something it does in fact do" — so this goes in `SnakeSyntax`
next to `has_ilike`, and not into `Cap`.

THE TRAP, and it is why this file asks about parameters: `emit_value` APPENDS to `params`. Writing
the fallback by reusing the emitted string would put the placeholder in twice while the value went
in once — and the dialect that needs the fallback is the one with counted placeholders. The
expression is emitted twice, properly, so N placeholders match N parameters.
"""

from __future__ import annotations

import pytest

from snakeorm.decorators import snake_model
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.dialects.base import SnakeDialect
from snakeorm.fields import SnakeColumn, snake_int, snake_str
from snakeorm.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery


@snake_model(table="no_users")
class _User(SnakeModel):
    """A model with a nullable-ish column to sort by."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    nickname: SnakeColumn[str] = snake_str()


snake_link()

_NATIVE: list[SnakeDialect] = [PostgresDialect(), SQLiteDialect()]


@pytest.mark.parametrize("dialect", _NATIVE, ids=lambda d: type(d).__name__)
def test_an_engine_with_the_keyword_still_gets_the_keyword(
    dialect: SnakeDialect,
) -> None:
    """Postgres and SQLite spell it natively, and must keep doing so.

    The fallback is portable but it costs an extra sort key, so an engine that has the keyword
    should not be paying for one.
    """
    sql, _ = (
        SnakeQuery(_User).order_by(_User.nickname.asc().nulls_last()).to_sql(dialect)
    )

    assert "NULLS LAST" in sql


def test_mysql_gets_the_portable_spelling_instead() -> None:
    """MySQL and MariaDB both refuse `NULLS LAST`, so the emitter writes `(x IS NULL)` first.

    Verified against both servers: the translation returns the same rows, inside a UNION too.
    """
    sql, _ = (
        SnakeQuery(_User)
        .order_by(_User.nickname.asc().nulls_last())
        .to_sql(MySQLDialect())
    )

    assert "NULLS" not in sql, "it emitted syntax MySQL answers 1064 to"
    assert "IS NULL" in sql


def test_nulls_first_and_last_sort_the_opposite_way_round() -> None:
    """The fallback has to mean what it says: FIRST and LAST cannot emit the same thing.

    A translation that ignored the direction would satisfy the test above and silently sort every
    query the same way — which is worse than the 1064, because it runs.
    """
    last, _ = (
        SnakeQuery(_User)
        .order_by(_User.nickname.asc().nulls_last())
        .to_sql(MySQLDialect())
    )
    first, _ = (
        SnakeQuery(_User)
        .order_by(_User.nickname.asc().nulls_first())
        .to_sql(MySQLDialect())
    )

    assert last != first


def test_the_placeholders_still_match_the_parameters() -> None:
    """Emitting the expression twice must not put a placeholder in twice for one value.

    `emit_value` appends to `params`, so a fallback written by reusing the emitted STRING would
    leave MySQL with two `%s` and one parameter — and MySQL is exactly the dialect that needs the
    fallback. The filter here puts a real parameter in the statement so the count can be checked.
    """
    dialect = MySQLDialect()
    sql, params = (
        SnakeQuery(_User)
        .filter(_User.nickname == "ana")
        .order_by(_User.nickname.asc().nulls_last())
        .to_sql(dialect)
    )

    assert sql.count(dialect.placeholder(1)) == len(params), (
        f"{sql.count(dialect.placeholder(1))} placeholders for {len(params)} parameters"
    )


def test_an_order_without_nulls_is_untouched_everywhere() -> None:
    """The floor: only a key that ASKED for nulls ordering changes shape.

    Without it, "write the portable form" could be implemented as "always write it" and every query
    in the ORM would grow a sort key nobody requested.
    """
    every: list[SnakeDialect] = [*_NATIVE, MySQLDialect()]
    for dialect in every:
        sql, _ = SnakeQuery(_User).order_by(_User.nickname.asc()).to_sql(dialect)

        assert "IS NULL" not in sql
        assert "NULLS" not in sql
