"""A condition may carry a COLUMN on its right-hand side, not only a literal.

`("a" - "b") > 0` already worked, because arithmetic emits each operand by asking whether it is an
expression or a value. A plain `"a" > "b"` did not, and the way it failed is the reason this file
exists rather than a footnote in the limits page.

WHAT IT USED TO DO. The comparison branch sent its right-hand side straight to `emit_operand`, which
appends whatever it is given to `params`. So `Stock.quantity > Stock.reserved` emitted SQL of the
RIGHT SHAPE — `WHERE "quantity" > ?` — with a `SnakeExpr` OBJECT bound as the parameter. Measured
against SQLite with seeded rows:

    ProgrammingError | Error binding parameter 1: type 'SnakeExpr' is not supported

It never answered wrongly, which is the one mercy in it. But the thing that spoke was the DRIVER,
about a type the user has never heard of, on a query that reads perfectly: "available = quantity
minus reserved" is the most ordinary question a warehouse has. In an ORM whose doctrine is that the
message IS the product, a driver-level `TypeError` standing in for "this ORM cannot do that yet" is
not a missing feature. It is the ORM failing to say anything at all.

THE RULE IS NOW THE SAME ONE ARITHMETIC ALREADY USED: an operand that is a `SnakeValue` is emitted
as a reference and consumes no parameter; anything else is a literal and travels in `params`. It is
not a new concept, it is the concept applied where it was missing.

AND THE SIBLINGS COME TOO, which is the lesson entry #18 of the bug journal paid for: `count()` was
fixed and its two brothers were left, by the very session that had just written down the pattern.
`LIKE` and `IN` take a right-hand side from the user in the same way, so all three go through the
same rule. Their TYPES stay closed — nothing asks to write `a LIKE b` today, and opening the
signature without a caller is how a surface grows things nobody uses — but at the emitter there is
now no shape that binds an expression object as a parameter.
"""

from __future__ import annotations

from snakeorm.dialects import PostgresDialect
from snakeorm.expressions import SnakeExpr
from snakeorm.sql.condition import emit_condition


def _sql(condition: object) -> tuple[str, list[object]]:
    """The emitted condition and the parameters it consumed."""
    sql, params = emit_condition(condition, PostgresDialect())  # type: ignore[arg-type]
    return sql, list(params)


def test_a_column_on_the_right_is_a_reference_and_costs_no_parameter() -> None:
    """The whole point: `"a" > "b"`, and `params` stays empty."""
    left: SnakeExpr[int] = SnakeExpr(path=("quantity",))
    right: SnakeExpr[int] = SnakeExpr(path=("reserved",))

    sql, params = _sql(left > right)

    assert sql == '"quantity" > "reserved"'
    assert params == []


def test_a_literal_on_the_right_still_travels_as_a_parameter() -> None:
    """The other half, and the one a fix like this breaks: values are NEVER interpolated.

    Parameterised SQL is what kills injection and what makes the multi-engine seam possible, so a
    change that teaches the emitter to write a column has to leave the literal path untouched.
    """
    left: SnakeExpr[int] = SnakeExpr(path=("quantity",))

    sql, params = _sql(left > 3)

    assert sql == '"quantity" > %s'
    assert params == [3]


def test_an_arithmetic_on_the_right_is_a_reference_too() -> None:
    """`"a" > ("b" - "c")`: the rule composes, because it is the rule arithmetic already used."""
    quantity: SnakeExpr[int] = SnakeExpr(path=("quantity",))
    reserved: SnakeExpr[int] = SnakeExpr(path=("reserved",))
    minimum: SnakeExpr[int] = SnakeExpr(path=("minimum",))

    sql, params = _sql(quantity > (reserved + minimum))

    assert sql == '"quantity" > ("reserved" + "minimum")'
    assert params == []


def test_equality_against_a_column_is_not_a_parameter_either() -> None:
    """`==` goes through the same branch, and its `None` shortcut must survive it."""
    left: SnakeExpr[int] = SnakeExpr(path=("a",))
    right: SnakeExpr[int] = SnakeExpr(path=("b",))

    assert _sql(left == right) == ('"a" = "b"', [])
    assert _sql(left == 1) == ('"a" = %s', [1])
    assert _sql(left == None) == ('"a" IS NULL', [])  # noqa: E711 - the shortcut IS the subject


def test_like_takes_a_column_without_binding_an_object() -> None:
    """The first sibling: nothing here may bind an expression as a parameter.

    `LIKE` is not typed open — no caller asks for `a LIKE b` today — but the emitter must not have a
    shape left in it that hands a `SnakeExpr` to the driver. That asymmetry is what entry #18 of the
    bug journal is about: the pattern was recognised and the brothers were left behind anyway.
    """
    column: SnakeExpr[str] = SnakeExpr(path=("name",))
    other: SnakeExpr[str] = SnakeExpr(path=("nickname",))

    sql, params = _sql(column.like(other))  # type: ignore[arg-type]

    assert sql == '"name" LIKE "nickname"'
    assert params == []


def test_in_takes_columns_without_binding_objects() -> None:
    """The second sibling, with the same argument and the same closed signature."""
    column: SnakeExpr[int] = SnakeExpr(path=("a",))
    first: SnakeExpr[int] = SnakeExpr(path=("b",))

    sql, params = _sql(column.in_([first, 2]))  # type: ignore[list-item]

    assert sql == '"a" IN ("b", %s)'
    assert params == [2]
