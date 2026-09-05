r"""`LIKE`/`ILIKE`: wildcard escaping and the per-engine case-insensitive fallback.

Two bugs that review reproduced live against SQLite:
1. `startswith/contains/endswith` escape the wildcards in the VALUE with `\`, but emission was not
   adding `ESCAPE '\'`. On Postgres it got away with it (its LIKE takes `\` as the default escape);
   on SQLite it did not, and the filter returned the WRONG set in silence.
2. `ilike/istartswith/...` emitted `ILIKE` unconditionally, which on SQLite is a syntax error.

The fix: `ESCAPE '\'` when the pattern was escaped (the `escaped` flag), and `LOWER(a) LIKE LOWER(b)`
as the portable fallback where there is no `ILIKE` (SQLite).
"""

from __future__ import annotations

import sqlite3

from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.sql import emit_condition


def _text() -> SnakeExpr[str]:
    return SnakeExpr[str](path=("texto",))


def test_startswith_emits_escape_clause() -> None:
    """Checks that a pattern with escaped wildcards carries `ESCAPE '\\'`, or SQLite misreads it."""
    sql, params = emit_condition(_text().startswith("100%"), PostgresDialect())
    assert sql == "\"texto\" LIKE %s ESCAPE '\\'"
    assert params == (
        "100\\%%",
    )  # the value's % is escaped; the trailing % is the real wildcard


def test_raw_like_has_no_escape_clause() -> None:
    """Checks that a raw `.like()` does NOT add ESCAPE: the user supplies their own wildcards."""
    sql, _ = emit_condition(_text().like("%an%"), PostgresDialect())
    assert sql == '"texto" LIKE %s'
    assert "ESCAPE" not in sql


def test_ilike_falls_back_to_lower_on_sqlite() -> None:
    """Checks that on SQLite (no ILIKE) we emit `LOWER(a) LIKE LOWER(b)`, not an ILIKE that blows up."""
    sql, _ = emit_condition(_text().ilike("%AbC%"), SQLiteDialect())
    assert sql == 'LOWER("texto") LIKE LOWER(?)'
    assert "ILIKE" not in sql


def test_ilike_uses_native_operator_on_postgres() -> None:
    """Checks that on Postgres we do use the native ILIKE."""
    sql, _ = emit_condition(_text().ilike("%AbC%"), PostgresDialect())
    assert sql == '"texto" ILIKE %s'


def test_istartswith_on_sqlite_combines_lower_and_escape() -> None:
    """Checks the combined case: case-insensitive AND escaped wildcards on SQLite."""
    sql, _ = emit_condition(_text().istartswith("a%b"), SQLiteDialect())
    assert sql == "LOWER(\"texto\") LIKE LOWER(?) ESCAPE '\\'"


def test_startswith_with_wildcard_matches_correctly_on_live_sqlite() -> None:
    """THE correctness test: `startswith('100%')` on real SQLite brings back ONLY the right rows.

    Before ESCAPE it returned `[]` (it lost '100%off') because the pattern's `\\` was taken literally.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (texto TEXT)")
    conn.executemany(
        "INSERT INTO t VALUES (?)", [("100%off",), ("100abc",), ("other",)]
    )
    sql, params = emit_condition(_text().startswith("100%"), SQLiteDialect())
    rows = [r[0] for r in conn.execute(f"SELECT texto FROM t WHERE {sql}", params)]
    assert rows == ["100%off"]  # neither '100abc' (the % is literal) nor 'other'
    conn.close()


def test_ilike_runs_without_syntax_error_on_live_sqlite() -> None:
    """Checks that `.ilike()` RUNS on SQLite (before: OperationalError near ILIKE) and folds ASCII."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (texto TEXT)")
    conn.executemany("INSERT INTO t VALUES (?)", [("Hola",), ("HOLA",), ("chau",)])
    sql, params = emit_condition(_text().ilike("hola"), SQLiteDialect())
    rows = sorted(
        r[0] for r in conn.execute(f"SELECT texto FROM t WHERE {sql}", params)
    )
    assert rows == ["HOLA", "Hola"]  # both ASCII capitalisation variants
    conn.close()


def test_every_dialect_writes_the_escape_character_the_way_its_engine_reads_it() -> (
    None
):
    """The ESCAPE clause is emitted through `dialect.literal()`, not as a hardcoded `'\\'`.

    The escape CHARACTER is the backslash on all three engines, and that is decided up in
    `_escape_like`, which is engine-agnostic and stays that way. What differs is how the engine
    reads that character INSIDE a string literal, and writing a literal is the dialect's whole job.

    MySQL is the one that breaks: the backslash is its string escape, so `ESCAPE '\\'` is not the
    one-character string it looks like — it is an unterminated literal. Measured against MariaDB
    11.8.8: `SELECT 'abc' LIKE 'a%' ESCAPE '\\'` answers ERROR 1064, so `startswith`, `contains`
    and `endswith` did not work on MySQL AT ALL. This file is where it hid: it imported two
    dialects out of three, so the whole suite agreed on a clause the third engine rejects.

    Which is why the check is over EVERY dialect and not over MySQL: pinning the engine that
    happened to be broken today would leave the fourth one to discover it again.
    """
    for dialect in (PostgresDialect(), MySQLDialect(), SQLiteDialect()):
        sql, _ = emit_condition(_text().startswith("100%"), dialect)
        expected = f"ESCAPE {dialect.literal(chr(92))}"

        assert expected in sql, (
            f"{type(dialect).__name__} emitted {sql!r}; the ESCAPE must be written with "
            f"literal(), which for this engine gives {expected!r}"
        )
