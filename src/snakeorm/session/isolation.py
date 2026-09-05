"""Transaction isolation levels."""

from __future__ import annotations

from enum import Enum


class SnakeIsolation(Enum):
    """What a transaction sees of what the others are doing while it is alive.

    STANDARD SQL values (not engine jargon), the other half of concurrency control alongside
    `for_update()`: the lock says which rows you reserve, the isolation what you see meanwhile.

    - `READ_COMMITTED`: each statement sees what was committed at its instant (Postgres default).
    - `REPEATABLE_READ`: a still photo of the whole transaction; a write conflict aborts it.
    - `SERIALIZABLE`: as if they ran single file. The strongest guarantee and the one that aborts most.
    - `READ_UNCOMMITTED`: for standard completeness; Postgres treats it as `READ COMMITTED`.
    """

    READ_UNCOMMITTED = "READ UNCOMMITTED"
    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"
