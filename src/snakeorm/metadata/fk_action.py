"""Referential actions of a foreign key (ON DELETE / ON UPDATE)."""

from __future__ import annotations

from enum import Enum


class SnakeFkAction(Enum):
    """Referential action of an FK, valid for both ON DELETE and ON UPDATE.

    Typed constants instead of magic strings. Each member's `value` is its SQL
    fragment, ready for the DDL generator.
    """

    NO_ACTION = "NO ACTION"
    RESTRICT = "RESTRICT"
    CASCADE = "CASCADE"
    SET_NULL = "SET NULL"
    SET_DEFAULT = "SET DEFAULT"
