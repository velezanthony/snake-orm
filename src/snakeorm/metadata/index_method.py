"""Access method of an index, declared ENGINE-AGNOSTIC."""

from __future__ import annotations

from enum import Enum


class SnakeIndexMethod(Enum):
    """Structure the engine builds the index with.

    Agnostic values (the dialect translates). `BTREE` is the de facto default and is emitted
    IMPLICITLY (no `USING`).
    """

    BTREE = "btree"  # the usual one: equality and ordered ranges
    HASH = "hash"  # equality only, more compact
    GIN = "gin"  # composite values: JSONB, arrays, text search
    GIST = "gist"  # geometry, ranges, proximity
    BRIN = "brin"  # huge tables whose data correlates with physical order
