"""Tests for SnakeValue (the base) and SnakeArith: paths, arithmetic, and reflected-operand order.

SnakeValue is the common base: it knows how to compare and how to do arithmetic. SnakeExpr (a
column) is the ONLY one with a `.path`; SnakeArith (an operation) recursively collects the paths of
its operands. Reflected operators respect order (`1 - a` != `a - 1`), which matters for `-` and `/`.
"""

from __future__ import annotations

from snakeorm.expressions import (
    SnakeArith,
    SnakeArithOp,
    SnakeComparison,
    SnakeCondition,
    SnakeExpr,
    SnakeValue,
)


def test_snake_expr_is_a_snake_value() -> None:
    """Checks that SnakeExpr is a SnakeValue (it inherits the comparators and the arithmetic)."""
    assert isinstance(SnakeExpr[int](path=("age",)), SnakeValue)


def test_snake_expr_paths_returns_its_own_path() -> None:
    """Checks that SnakeExpr.paths() returns a tuple holding its single column path."""
    assert SnakeExpr[int](path=("age",)).paths() == (("age",),)


def test_base_exposes_comparators() -> None:
    """Checks that any SnakeValue at all (here a SnakeArith) can be compared."""
    arith = SnakeExpr[int](path=("id",)) + 1
    condition = arith > 3
    assert isinstance(condition, SnakeComparison)
    assert isinstance(condition, SnakeCondition)


def test_add_builds_snake_arith_with_correct_order() -> None:
    """Checks that `column + value` produces a SnakeArith with op ADD and its operands in order."""
    node = SnakeExpr[int](path=("id",)) + 1
    assert isinstance(node, SnakeArith)
    assert node.op is SnakeArithOp.ADD
    assert isinstance(node.left, SnakeExpr)
    assert node.left.path == ("id",)
    assert node.right == 1


def test_arith_paths_collects_operand_paths() -> None:
    """Checks that SnakeArith.paths() collects the paths of both of its column operands."""
    node = SnakeExpr[int](path=("a",)) + SnakeExpr[int](path=("b",))
    assert node.paths() == (("a",), ("b",))


def test_arith_paths_recurse_into_nested_operations() -> None:
    """Checks that paths() descends recursively: `(a + 1) * b` collects a and b (not the literal)."""
    node = (SnakeExpr[int](path=("a",)) + 1) * SnakeExpr[int](path=("b",))
    assert node.paths() == (("a",), ("b",))


def test_arith_paths_ignores_literal_operands() -> None:
    """Checks that a literal operand contributes no paths: only columns count."""
    node = SnakeExpr[int](path=("a",)) + 1
    assert node.paths() == (("a",),)


def test_reflected_subtraction_respects_order() -> None:
    """Checks that `1 - a` != `a - 1`: the reflected form swaps the operands (order matters)."""
    column = SnakeExpr[int](path=("a",))
    reflected = 1 - column
    direct = column - 1
    assert reflected.op is SnakeArithOp.SUB
    assert reflected.left == 1
    assert isinstance(reflected.right, SnakeExpr)
    assert reflected.right.path == ("a",)
    assert isinstance(direct.left, SnakeExpr)
    assert direct.left.path == ("a",)
    assert direct.right == 1


def test_reflected_division_respects_order() -> None:
    """Checks the same ordering with division: `10 / a` leaves the literal on the left."""
    column = SnakeExpr[int](path=("a",))
    reflected = 10 / column
    assert reflected.op is SnakeArithOp.DIV
    assert reflected.left == 10
    assert isinstance(reflected.right, SnakeExpr)
    assert reflected.right.path == ("a",)


def test_base_paths_is_abstract() -> None:
    """Checks that the SnakeValue base cannot hand out paths on its own (subclasses define that)."""
    import pytest

    with pytest.raises(NotImplementedError):
        SnakeValue[int]().paths()
