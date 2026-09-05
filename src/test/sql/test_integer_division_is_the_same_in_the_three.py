"""`Stock.reserved / Stock.on_hand` must mean the SAME thing on the three engines.

IT DID NOT, AND THE TYPE WAS THE ONE LYING. Measured by running `SELECT 45/50` against each engine:

    PostgreSQL   0          integer          (pg_typeof)
    SQLite       0          integer
    MySQL        0.9000     decimal(6,4)     -- and `45 DIV 50` is 0

`__truediv__` is `SnakeValue[T] | T -> SnakeArith[T]`: two integer columns are declared
`SnakeArith[int]`. On two engines that is true. On MySQL it is FALSE — a `Decimal` arrives where the
checker promised an `int` — and nothing caught it, because the emitter wrote the same `/` for all
three and `/` does not mean the same thing in all three. MySQL keeps `DIV` as a SEPARATE operator
precisely because its `/` is not integer division.

In an ORM whose thesis is that the type system is the only source of truth, a type that holds on two
engines out of three is the whole thesis leaking. So the dialect spells the operator, for the same
reason it already spells placeholders and `LIMIT`: what the SQL SAYS is the dialect's business, what
it MEANS is the graph's.

IT ONLY ACTS ON PROOF. The emitter switches operator only when BOTH operands are demonstrably
integers — a column whose compiled type says so, an `int` literal, a cast to `int`, or an arithmetic
node built from those. Anything it cannot prove is emitted as `/`, exactly as before. A guess in
either direction would be worse than the bug: silently turning a genuine decimal division into an
integer one loses data, and this ORM does not produce a wrong answer with no error.
"""

from __future__ import annotations

from snakeorm import SnakeColumn, snake_auto, snake_column, snake_model
from snakeorm.dialects import MySQLDialect, PostgresDialect, SQLiteDialect
from snakeorm.expressions import SnakeExpr, snake_cast
from snakeorm.model import SnakeModel
from snakeorm.sql.value import emit_value


@snake_model(table="idiv_stock")
class _Stock(SnakeModel):
    """Two integer columns and one float, which is what tells the two branches apart."""

    id: SnakeColumn[int] = snake_auto()
    reserved: SnakeColumn[int] = snake_column()
    on_hand: SnakeColumn[int] = snake_column()
    weight: SnakeColumn[float] = snake_column()


def test_mysql_writes_div_when_both_operands_are_integers() -> None:
    """MySQL's `/` returns a decimal, so integer division has to be asked for by its own name."""
    sql = emit_value(_Stock.reserved / _Stock.on_hand, MySQLDialect(), [], None)
    assert sql == "(`reserved` DIV `on_hand`)"


def test_postgres_and_sqlite_keep_the_slash_because_theirs_is_already_integer() -> None:
    """Neither engine needs anything: `/` between integers is integer division in both."""
    for dialect, expected in (
        (PostgresDialect(), '("reserved" / "on_hand")'),
        (SQLiteDialect(), '("reserved" / "on_hand")'),
    ):
        assert (
            emit_value(_Stock.reserved / _Stock.on_hand, dialect, [], None) == expected
        )


def test_the_three_engines_now_agree_on_what_the_expression_says() -> None:
    """The point of the whole file: one meaning, three spellings, and the declared type is true."""
    node = _Stock.reserved / _Stock.on_hand
    emitted = {
        type(dialect).__name__: emit_value(node, dialect, [], None)
        for dialect in (PostgresDialect(), SQLiteDialect(), MySQLDialect())
    }
    assert emitted["MySQLDialect"] == "(`reserved` DIV `on_hand`)"
    assert (
        emitted["PostgresDialect"]
        == emitted["SQLiteDialect"]
        == '("reserved" / "on_hand")'
    )


def test_an_integer_literal_is_proof_enough() -> None:
    """`Stock.reserved / 2` is integer division too, and the literal still travels as a param."""
    params: list[object] = []
    sql = emit_value(_Stock.reserved / 2, MySQLDialect(), params, None)
    assert sql == "(`reserved` DIV %s)"
    assert params == [2]


def test_a_float_column_is_not_touched() -> None:
    """The other branch: a decimal division stays `/` on MySQL, which is what it must be."""
    assert (
        emit_value(_Stock.weight / 2.0, MySQLDialect(), [], None) == "(`weight` / %s)"
    )


def test_a_cast_to_float_disarms_the_switch() -> None:
    """`snake_cast(x, float)` says the arithmetic is decimal: MySQL must NOT write DIV then."""
    node = snake_cast(_Stock.reserved, float) / snake_cast(_Stock.on_hand, float)
    assert emit_value(node, MySQLDialect(), [], None) == (
        "(CAST(`reserved` AS DOUBLE) / CAST(`on_hand` AS DOUBLE))"
    )


def test_an_unprovable_operand_is_left_exactly_as_it_was() -> None:
    """CONSERVATIVE BY DESIGN: a bare `SnakeExpr` carries no compiled type, so nothing changes.

    This is the test that keeps the feature honest. Guessing `int` here would turn somebody's decimal
    division into an integer one without a word, which is a worse failure than the one being fixed.
    """
    bare: SnakeExpr[int] = SnakeExpr(path=("mystery",))
    assert (
        emit_value(bare / bare, MySQLDialect(), [], None) == "(`mystery` / `mystery`)"
    )


def test_only_division_changes_and_the_other_operators_are_untouched() -> None:
    """`+`, `-` and `*` mean the same in the three engines: nothing to translate, nothing touched."""
    for node, expected in (
        (_Stock.reserved + _Stock.on_hand, "(`reserved` + `on_hand`)"),
        (_Stock.reserved - _Stock.on_hand, "(`reserved` - `on_hand`)"),
        (_Stock.reserved * _Stock.on_hand, "(`reserved` * `on_hand`)"),
    ):
        assert emit_value(node, MySQLDialect(), [], None) == expected
