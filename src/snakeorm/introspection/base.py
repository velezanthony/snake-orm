"""The INTROSPECTOR Protocol: how a database's schema is READ (the third axis, alongside Dialect and Driver).

It returns the SAME graph (`SnakeTableInfo`) as the Model Compiler: scaffolding and the drift `check` compare with no translator. It is NOT bijective: `TEXT`/`VARCHAR(50)`/`CHAR(10)` all come back as `str`, so the round trip does not reproduce the original.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.metadata import SnakeTableInfo


@runtime_checkable
class SnakeIntrospector(Protocol):
    """Reads a database's REAL schema and returns it as a metadata graph."""

    def tables(self, schema: str = DEFAULT_SCHEMA) -> list[SnakeTableInfo]:
        """Every table in the schema with its columns, PK, uniqueness, indexes and comments.

        The FKs come resolved in each `SnakeTableInfo` pointing at the NAME of the target table; whoever generates models translates them into class names.
        """
        ...

    def unsupported(self, schema: str = DEFAULT_SCHEMA) -> list[str]:
        """Objects the ORM does NOT know how to represent (triggers, exotic types, expression indexes), described so it can WARN.

        Dropping them silently would make people believe the generated model covers the whole database.
        """
        ...
