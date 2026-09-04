"""Storage size of an integer in the DATABASE (not in Python)."""

from __future__ import annotations

from enum import StrEnum


class SnakeIntSize(StrEnum):
    """How many bits an `int` reserves in the database.

    Python always uses an unbounded `int`; this only decides how much room the engine takes. The
    members are the SQL STANDARD (which is why the `StrEnum` earns its type); the dialect
    translates (SQLite collapses them all to `INTEGER`). `BIGINT` is the default on purpose: it is
    the widest of both engines, so Python's uncapped `int` lines up in Postgres and SQLite. You
    step it down by hand when saving bytes matters.
    """

    SMALLINT = "SMALLINT"  # 16 signed bits (±32,767)
    INTEGER = "INTEGER"  # 32 signed bits (±2,147,483,647)
    BIGINT = "BIGINT"  # 64 signed bits (±9.2·10¹⁸) — DEFAULT: the engine's widest
