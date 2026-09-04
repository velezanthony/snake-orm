"""Tests of the AST order keys: .asc() and .desc() on a column.

They produce a SnakeOrder (column + direction). Any column is orderable, with no restriction.
"""

from __future__ import annotations

from snakeorm.expressions import SnakeExpr, SnakeOrder


def test_asc_builds_ascending_order() -> None:
    """Checks that `.asc()` produces an ascending SnakeOrder carrying the column."""
    key = SnakeExpr[str](path=("username",)).asc()
    assert isinstance(key, SnakeOrder)
    assert isinstance(key.expr, SnakeExpr)
    assert key.expr.path == ("username",)
    assert key.descending is False


def test_desc_builds_descending_order() -> None:
    """Checks that `.desc()` produces a descending SnakeOrder."""
    key = SnakeExpr[int](path=("age",)).desc()
    assert isinstance(key, SnakeOrder)
    assert key.descending is True
