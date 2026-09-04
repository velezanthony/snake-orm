"""What a graph node IS and WHO governs it."""

from __future__ import annotations

from enum import Enum


class SnakeTableKind(Enum):
    """Nature of a graph node: one single axis, not a bag of booleans.

    Replaces `is_view`/`managed`: N booleans give you illegal states (a managed external view?);
    the enum makes them unwritable. `database` does NOT belong here (an axis independent of what
    the node is).

    - `TABLE`: a table we manage (create/alter/drop).
    - `VIEW`: a view we manage (`@snake_view`). READ ONLY, no constraints.
    - `EXTERNAL`: a mirror of something existing that we do NOT govern (`@snake_db_first`);
      migrations IGNORE it.
    """

    TABLE = "table"
    VIEW = "view"
    EXTERNAL = "external"
