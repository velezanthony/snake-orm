"""Reading INSIDE a JSON column: `meta.json_get("size", as_type=int) > 100`.

`snake_json()` could store a document and nothing could filter by a key in it, which made the type
half a feature: the value went in and came out whole, and the engine — which knows perfectly well how
to look inside — was never asked.

THE DECISION THIS FILE PINS IS THE TYPE, and it is the one that decides everything else. The other
option was for a key access to be `SnakeExpr[str]` always, on the grounds that `->>` returns text and
the user can cast. It reads as the honest choice and it is the opposite: it would let
`meta.json_get("size") > 100` compare TEXT, where `'9' > '100'` is true. That is the same trap the
capability catalogue already documents for a `Decimal` ordered as TEXT on SQLite — and this project
declares that one loudly rather than letting it pass.

So the type is DECLARED at the call site and the ORM emits the CAST. If the document does not hold
what was declared, the DATABASE says so, which is the right place for that complaint: the ORM cannot
know what is inside a document it did not write.

EACH ENGINE WRITES IT DIFFERENTLY, so the emission belongs to the dialect and not to the node. That
is the same seam as placeholders and `LIMIT`: what the SQL SAYS is the dialect's, what it MEANS is
the graph's. The three spellings are pinned below because they are what a reader has to trust.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeQuery,
    SnakeSession,
    SQLiteDriver,
    snake_auto,
    snake_json,
    snake_model,
    snake_table,
)
from snakeorm.core.exceptions import SnakeUnsupportedFeature, SnakeValueError
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.migration import emit_create_table
from snakeorm.model import SnakeModel
from snakeorm.sql.condition import emit_condition


@snake_model(table="jsa_docs")
class _Doc(SnakeModel):
    """A document with free-form metadata, for the end-to-end half of this file."""

    id: SnakeColumn[int] = snake_auto()
    meta: SnakeColumn[dict] = snake_json()


def _column() -> SnakeExpr[dict]:
    """A JSON column, as the descriptor hands it over on class access."""
    return SnakeExpr(path=("meta",))


def test_postgres_uses_the_arrow_and_casts_what_was_declared() -> None:
    """`->>` gives text, so the declared type is what turns it into a comparison that means it."""
    sql, params = emit_condition(
        _column().json_get("size", as_type=int) > 100, PostgresDialect()
    )

    assert sql == "((\"meta\" ->> 'size'))::integer > %s"
    assert params == (100,)


def test_sqlite_uses_json_extract() -> None:
    """SQLite's `json_extract` already returns a typed value; the CAST pins it anyway."""
    sql, params = emit_condition(
        _column().json_get("size", as_type=int) > 100, SQLiteDialect()
    )

    assert sql == "CAST(json_extract(\"meta\", '$.size') AS INTEGER) > ?"
    assert params == (100,)


def test_mysql_unquotes_before_casting() -> None:
    """`JSON_EXTRACT` returns a JSON scalar, so the quotes come off before the cast."""
    sql, params = emit_condition(
        _column().json_get("size", as_type=int) > 100, MySQLDialect()
    )

    assert sql == ("CAST(JSON_UNQUOTE(JSON_EXTRACT(`meta`, '$.size')) AS SIGNED) > %s")
    assert params == (100,)


def test_a_nested_path_is_one_access_and_not_two() -> None:
    """`json_get("a", "b")` walks the document once: the engines all take a path."""
    sql, _ = emit_condition(
        _column().json_get("owner", "name", as_type=str) == "ada", PostgresDialect()
    )

    assert "'{owner,name}'" in sql, sql


def test_a_string_key_needs_no_cast() -> None:
    """Text out of a document is already text: casting it would be noise in every statement."""
    sql, params = emit_condition(
        _column().json_get("name", as_type=str) == "ada", PostgresDialect()
    )

    assert sql == "(\"meta\" ->> 'name') = %s"
    assert params == ("ada",)


def test_the_key_is_not_a_parameter_and_is_refused_if_it_could_inject() -> None:
    """A key is part of the STATEMENT, not a value, so it is validated instead of parametrised.

    Every engine wants the path inside a literal (`'$.a'`, `'{a,b}'`), where a placeholder cannot go.
    That is precisely the shape where an unchecked string becomes an injection, so a key that is not
    a plain identifier is refused when the expression is built.
    """
    with pytest.raises(SnakeValueError, match="key"):
        _column().json_get("a'; DROP TABLE x --", as_type=str)


def test_an_unsupported_declared_type_is_refused_by_name() -> None:
    """What the ORM cannot cast to, it says. It does not emit a cast the engine will reject."""
    with pytest.raises(SnakeUnsupportedFeature, match="json_get"):
        _column().json_get("when", as_type=complex) == 1  # type: ignore[type-var]


def test_the_engine_agrees_with_the_declared_type() -> None:
    """The emission is only half of it: the ENGINE has to return the right rows.

    Run against SQLite because it is the engine most likely to disagree — `json_extract` gives back
    whatever the document held, so a size stored as text would come back as text and the comparison
    would be lexicographic. This is where the CAST earns its keep: without it `9 > 10` is true, since
    as TEXT it is `'9' > '10'`.
    """
    dialect = SQLiteDialect()
    driver = SQLiteDriver.connect(":memory:")
    driver.execute(emit_create_table(snake_table(_Doc), dialect), ())
    driver.commit()
    session = SnakeSession(driver, dialect)
    for size in (9, 100, 7):
        session.add(_Doc(meta={"size": size, "owner": {"name": f"n{size}"}}))
    session.commit()

    bigger = session.all(
        SnakeQuery(_Doc).filter(_Doc.meta.json_get("size", as_type=int) > 10)
    )

    assert [row.meta["size"] for row in bigger] == [100]
    # And the nested path, which is one trip through the document rather than two.
    named = session.all(
        SnakeQuery(_Doc).filter(
            _Doc.meta.json_get("owner", "name", as_type=str) == "n9"
        )
    )
    assert [row.meta["size"] for row in named] == [9]
