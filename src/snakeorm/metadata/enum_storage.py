"""How an enum is backed in the database."""

from __future__ import annotations

from enum import Enum


class SnakeEnumStorage(Enum):
    """Which DB object checks that the column only ever holds valid enum members.

    Engine-agnostic values (the dialect translates), like `SnakeServerDefault`/`SnakeFkAction`.

    - `CHECK` (default): the base type plus a `CHECK col IN (...)`. Adding a value is reversible;
      removing one fails at `migrate` if rows are still using it.
    - `PLAIN`: base type only, no validation. An invalid value slipped in through raw SQL blows up
      ON READ.

    The BASE TYPE is not spelled out here, and the omission is deliberate: this class picks the DB
    object that validates the column, not the SQL type, and the type is the dialect's answer to
    `storage_type`. Measured on the three: `SnakeColumnInfo.__post_init__` derives a text enum's
    width from its longest member, so a text-backed enum is `VARCHAR(n)` on PostgreSQL and MySQL
    and `TEXT` only on SQLite, which has affinities and no widths; an int-backed one is `BIGINT` on
    the first two and `INTEGER` on SQLite for the same reason.

    There is no `NATIVE` on purpose: in Postgres `ADD VALUE` has no inverse (recreating the type
    rewrites the table under `ACCESS EXCLUSIVE`), the value cannot be used in the same transaction
    that adds it (and migrations are transactional), and if two models share the enum they share
    the type. With `CHECK` none of that happens. A `NATIVE` that throws when used would be dead
    metadata.
    """

    CHECK = "check"
    PLAIN = "plain"
