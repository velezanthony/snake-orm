"""How a `dict` is backed in the database: normalised binary or exact text."""

from __future__ import annotations

from enum import StrEnum


class SnakeJsonStorage(StrEnum):
    """The DB object that stores a `dict`.

    Members = the literal name of the type in Postgres; the dialect translates (SQLite collapses
    both to TEXT).

    - `JSONB` (default): binary, indexable, NORMALISES (reorders keys, drops duplicates, loses
      `100.0` vs `100`). What nearly every real case wants.
    - `JSON`: stores the text as-is (not indexable, preserved bit for bit). It also makes Postgres
      line up with SQLite.
    """

    JSONB = "JSONB"  # binary, indexable, normalised — DEFAULT
    JSON = "JSON"  # exact text, not indexable
