"""Kind of explicit JOIN onto a collection: INNER and LEFT only (never RIGHT nor FULL)."""

from __future__ import annotations

from enum import Enum


class SnakeJoin(Enum):
    """How a collection is joined in an explicit `.join()` (projection only). INNER and LEFT only.

    Both preserve the ROOT as the non-nullable side (every row has its parent). RIGHT/FULL would
    bring up rows with the root at NULL, impossible to hydrate: illegal states unrepresentable.

    - INNER: only parents with at least one matching child (one row per child).
    - LEFT: on top of that, each childless parent once with the child's columns at NULL.
    """

    INNER = "INNER"
    LEFT = "LEFT"
