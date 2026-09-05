"""Tests of the new AST operators: in_, is_null, is_not_null, like and NOT (~).

Every method/operator builds its own condition node. The typing (self: SnakeExpr[str] on like,
values typed to T on in_) is checked separately with mypy and pyright, not at runtime.
"""

from __future__ import annotations

from snakeorm.expressions import (
    SnakeComparison,
    SnakeCondition,
    SnakeExpr,
    SnakeInList,
    SnakeIsNotNull,
    SnakeIsNull,
    SnakeLike,
    SnakeNot,
)


def test_in_builds_snake_in_list() -> None:
    """Checks that `.in_([...])` produces a SnakeInList with the column and the values."""
    node = SnakeExpr[int](path=("age",)).in_([1, 2, 3])
    assert isinstance(node, SnakeInList)
    assert isinstance(node.left, SnakeExpr)
    assert node.left.path == ("age",)
    assert node.values == (1, 2, 3)


def test_is_null_builds_snake_is_null() -> None:
    """Checks that `.is_null()` produces a SnakeIsNull over the column."""
    node = SnakeExpr[str](path=("username",)).is_null()
    assert isinstance(node, SnakeIsNull)
    assert isinstance(node.left, SnakeExpr)
    assert node.left.path == ("username",)


def test_is_not_null_builds_snake_is_not_null() -> None:
    """Checks that `.is_not_null()` produces a SnakeIsNotNull."""
    node = SnakeExpr[str](path=("username",)).is_not_null()
    assert isinstance(node, SnakeIsNotNull)


def test_like_builds_snake_like() -> None:
    """Checks that `.like(pattern)` produces a SnakeLike with the column and the pattern."""
    node = SnakeExpr[str](path=("username",)).like("%an%")
    assert isinstance(node, SnakeLike)
    assert isinstance(node.left, SnakeExpr)
    assert node.left.path == ("username",)
    assert node.pattern == "%an%"


def test_not_via_invert_builds_snake_not() -> None:
    """Checks that `~cond` produces a SnakeNot wrapping the original condition."""
    inner = SnakeExpr[str](path=("username",)) == "Ana"
    node = ~inner
    assert isinstance(node, SnakeNot)
    assert node.operand is inner


def test_eq_none_builds_is_null() -> None:
    """Checks that `column == None` produces IS NULL (not `= NULL`, always false in SQL)."""
    node = SnakeExpr[str](path=("username",)) == None  # noqa: E711
    assert isinstance(node, SnakeIsNull)


def test_ne_none_builds_is_not_null() -> None:
    """Checks that `column != None` produces IS NOT NULL."""
    node = SnakeExpr[str](path=("username",)) != None  # noqa: E711
    assert isinstance(node, SnakeIsNotNull)


def test_eq_value_still_builds_comparison() -> None:
    """Checks that with a plain value `==` still produces a comparison."""
    node = SnakeExpr[str](path=("username",)) == "Ana"
    assert isinstance(node, SnakeComparison)


def test_condition_nodes_are_snake_conditions() -> None:
    """Checks that every new node is a SnakeCondition (combinable with & | ~)."""
    expr = SnakeExpr[int](path=("age",))
    assert isinstance(expr.in_([1]), SnakeCondition)
    assert isinstance(expr.is_null(), SnakeCondition)
