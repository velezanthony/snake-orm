"""Fixtures that push `hints_of`'s type-checking fallback at the places it can plausibly break."""

from __future__ import annotations

from snakeorm.registry import SnakeRegistry

stress_registry = SnakeRegistry()
shop_registry = SnakeRegistry()
crm_registry = SnakeRegistry()
three_registry = SnakeRegistry()
