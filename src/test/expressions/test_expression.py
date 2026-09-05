"""Tests of the expression AST: SnakeExpr (a column) and SnakeCondition (a boolean).

SnakeExpr's operators produce conditions; conditions are combined with & and |. SnakeExpr's __eq__
does NOT return a bool (it returns a comparison), which is why nodes are checked field by field,
not with ==.
"""

from __future__ import annotations

import pytest

from snakeorm.expressions import (
    SnakeAnd,
    SnakeComparison,
    SnakeExpr,
    SnakeOp,
    SnakeOr,
)


def _name() -> SnakeExpr[str]:
    """Test expression for the 'username' column."""
    return SnakeExpr(path=("username",))


def test_eq_builds_comparison() -> None:
    """Checks that `==` produces a SnakeComparison with the EQ operator and its operands."""
    cond = _name() == "Ana"
    assert isinstance(cond, SnakeComparison)
    assert cond.op is SnakeOp.EQ
    assert isinstance(cond.left, SnakeExpr)
    assert cond.left.path == ("username",)
    assert cond.right == "Ana"


def test_lt_builds_comparison() -> None:
    """Checks that `<` produces a SnakeComparison with the LT operator."""
    cond = SnakeExpr[int](path=("age",)) < 18
    assert isinstance(cond, SnakeComparison)
    assert cond.op is SnakeOp.LT
    assert cond.right == 18


def test_expr_is_unhashable() -> None:
    """Checks that SnakeExpr is not hashable (its __eq__ does not return a bool)."""
    with pytest.raises(TypeError):
        hash(_name())


def test_and_builds_snake_and() -> None:
    """Checks that `&` between conditions produces a SnakeAnd holding both parts."""
    left = _name() == "Ana"
    right = SnakeExpr[int](path=("age",)) > 18
    combined = left & right
    assert isinstance(combined, SnakeAnd)
    assert combined.parts == (left, right)


def test_or_builds_snake_or() -> None:
    """Checks that `|` between conditions produces a SnakeOr holding both parts."""
    left = _name() == "Ana"
    right = _name() == "Bob"
    combined = left | right
    assert isinstance(combined, SnakeOr)
    assert combined.parts == (left, right)


def test_ne_builds_comparison() -> None:
    """Checks that `!=` produces a SnakeComparison with the NE operator."""
    cond = _name() != "Ana"
    assert isinstance(cond, SnakeComparison)
    assert cond.op is SnakeOp.NE


def test_le_gt_ge_build_comparisons() -> None:
    """Checks that `<=`, `>` and `>=` produce comparisons carrying their operator."""
    age = SnakeExpr[int](path=("age",))
    assert (age <= 18).op is SnakeOp.LE
    assert (age > 18).op is SnakeOp.GT
    assert (age >= 18).op is SnakeOp.GE
