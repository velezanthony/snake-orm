"""THE MATRIX: what every engine answers to every capability, in one place.

Here and not in each dialect because the question is horizontal — "what does each engine do about
this?" — and answering it meant opening four files. WHAT an engine can do lives here; HOW it does it
stays in its dialect.

It is also what makes MariaDB and MySQL two columns: one dialect serves both, and they differ.
"""

from __future__ import annotations

from enum import Enum, auto

from snakeorm.dialects.capabilities import (
    Cap,
    Degraded,
    Full,
    Nope,
    Since,
    SnakeCapabilities,
    Support,
)


class Engine(Enum):
    """The engines, one per column. MariaDB and MySQL are two: measured, they are not the same."""

    POSTGRES = auto()
    MARIADB = auto()
    MYSQL = auto()
    SQLITE = auto()


MATRIX: dict[Cap, dict[Engine, Support | Since]] = {
    Cap.RETURNING: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),  # `INSERT ... RETURNING id` answers the rows, measured 10.11-11.8
        Engine.MYSQL: Nope(
            "it has no RETURNING: the autoincrement PK is recovered with lastrowid, so a write that needs the returned rows makes one extra round trip"
        ),
        Engine.SQLITE: Full(),
    },
    Cap.ROW_CONSTRUCTOR: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Full(),
    },
    Cap.TRANSACTIONAL_DDL: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Nope(
            "DDL commits implicitly: an N-step migration is NOT all-or-nothing, and if step 3 fails, the first two are already applied"
        ),
        Engine.MYSQL: Nope(
            "DDL commits implicitly: an N-step migration is NOT all-or-nothing, and if step 3 fails, the first two are already applied"
        ),
        Engine.SQLITE: Full(),
    },
    Cap.UPSERT: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Full(),
    },
    Cap.CHECK_CONSTRAINT_DDL: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Since(
            (3, 53, 0),
            "ALTER TABLE ... ADD CONSTRAINT ... CHECK",
            below=Nope(
                "it does not accept ALTER TABLE ... ADD CONSTRAINT: a CHECK can only travel inside the CREATE TABLE, so putting one on an existing table takes rebuilding it, which is what `RebuildTable` does"
            ),
        ),
    },
    Cap.ADD_CONSTRAINT: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Nope(
            "it does not accept ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY: FKs go INSIDE the CREATE TABLE, so the plan emits them there and orders the tables topologically"
        ),
    },
    Cap.ALTER_COLUMN: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Nope(
            "it cannot change the type nor the nullability of an existing column: it would demand rebuilding the whole table"
        ),
    },
    Cap.SCHEMAS: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Nope(
            "it has no named schemas: in MySQL a 'schema' IS a database, not a namespace inside one"
        ),
        Engine.MYSQL: Nope(
            "it has no named schemas: in MySQL a 'schema' IS a database, not a namespace inside one"
        ),
        Engine.SQLITE: Nope(
            "it has no named schemas; its 'schemas' are ATTACHED databases (ATTACH)"
        ),
    },
    Cap.STORED_FUNCTIONS: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),  # `CREATE OR REPLACE FUNCTION`, which is what a re-run needs
        Engine.MYSQL: Nope(
            "a routine's body is raw SQL and replacing one relies on CREATE OR REPLACE FUNCTION, which MariaDB accepts and MySQL rejects outright. This dialect serves both, so it cannot promise what only one of them does"
        ),
        Engine.SQLITE: Nope(
            "it does not store functions: SQLite's are registered from the process that opens the connection, so they do not live in the database and a migration cannot create them"
        ),
    },
    Cap.ROW_LOCKING: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Nope(
            "it cannot lock rows (SELECT ... FOR UPDATE): it locks the whole FILE"
        ),
    },
    Cap.SET_ISOLATION: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Nope(
            "it has no SET TRANSACTION ISOLATION LEVEL: one writer at a time makes its transactions serialisable already, and the only knob it offers, PRAGMA read_uncommitted, LOWERS the isolation instead of raising it"
        ),
    },
    Cap.TEXT_IN_PRIMARY_KEY: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Nope(
            "a key needs a length and TEXT has none, so it answers error 1170 and the whole CREATE TABLE dies. Give the column a `max_length` and it becomes a VARCHAR"
        ),
        Engine.MYSQL: Nope(
            "a key needs a length and TEXT has none, so it answers error 1170 and the whole CREATE TABLE dies. Give the column a `max_length` and it becomes a VARCHAR"
        ),
        Engine.SQLITE: Full(),
    },
    Cap.COMMENTS: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Degraded(
            "it has no COMMENT ON: a table comment is a clause (CREATE TABLE ... COMMENT =, ALTER TABLE ... COMMENT =) and a COLUMN comment can only change by rewriting the whole column with MODIFY COLUMN. The definition is respelled from the model, so what the model declares survives; anything the database holds that the model does not describe (a collation, ON UPDATE CURRENT_TIMESTAMP, a generated expression) does not. An empty comment and no comment are also the same value here"
        ),
        Engine.MYSQL: Degraded(
            "it has no COMMENT ON: a table comment is a clause (CREATE TABLE ... COMMENT =, ALTER TABLE ... COMMENT =) and a COLUMN comment can only change by rewriting the whole column with MODIFY COLUMN. The definition is respelled from the model, so what the model declares survives; anything the database holds that the model does not describe (a collation, ON UPDATE CURRENT_TIMESTAMP, a generated expression) does not. An empty comment and no comment are also the same value here"
        ),
        Engine.SQLITE: Nope(
            "it does not store COMMENT ON, so db_comment values are omitted"
        ),
    },
    Cap.REPLACE_VIEW: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Nope(
            "it has no CREATE OR REPLACE VIEW: altering a view is emulated with DROP + CREATE"
        ),
    },
    Cap.PARENTHESISED_COMPOUND: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Nope(
            "it rejects parentheses in the branches of a UNION/EXCEPT/INTERSECT, so a LIMIT cannot be confined to one branch"
        ),
    },
    Cap.CTE_IN_COMPOUND_BRANCH: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Nope(
            "it does not accept a WITH RECURSIVE as a branch of a UNION/EXCEPT/INTERSECT (error 1064) even though it parenthesises branches perfectly well, so a recursion cannot be composed with a set operation: run it on its own"
        ),
        Engine.MYSQL: Full(),  # takes it as a branch of a compound, measured 8.0-9.7
        Engine.SQLITE: Nope(
            'it does not accept a WITH RECURSIVE as a branch of a UNION/EXCEPT/INTERSECT (near "WITH": syntax error), so a recursion cannot be composed with a set operation: run it on its own'
        ),
    },
    Cap.ILIKE: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Degraded(
            "it has no ILIKE, so the case-insensitive match is written LOWER(a) LIKE LOWER(b): it matches, and what it folds is whatever the column's collation folds, which is a decision of the schema and not of the query"
        ),
        Engine.MYSQL: Degraded(
            "it has no ILIKE, so the case-insensitive match is written LOWER(a) LIKE LOWER(b): it matches, and what it folds is whatever the column's collation folds, which is a decision of the schema and not of the query"
        ),
        Engine.SQLITE: Degraded(
            "it has no ILIKE: the case-insensitive match is written LOWER(a) LIKE LOWER(b), which matches and folds only ASCII"
        ),
    },
    Cap.INDEX_METHODS: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Degraded(
            "it has USING BTREE and HASH, but not the Postgres methods (GIN, GIST, BRIN)"
        ),
        Engine.MYSQL: Degraded(
            "it has USING BTREE and HASH, but not the Postgres methods (GIN, GIST, BRIN)"
        ),
        Engine.SQLITE: Nope(
            "it has only one kind of index, so it does not accept method= (GIN, GIST...)"
        ),
    },
    Cap.PARTIAL_INDEXES: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Nope(
            "it has no partial indexes: WHERE is not part of its CREATE INDEX, so a SEARCH index declared with where= is created over the WHOLE table — it finds the same rows and only costs more space — while a partial UNIQUE one is refused, because widening it would forbid duplicates the domain allows. If you need the partial uniqueness on this engine, enforce it with a generated column plus a plain UNIQUE over it, which is the one MySQL idiom that expresses the same rule"
        ),
        Engine.MYSQL: Nope(
            "it has no partial indexes: WHERE is not part of its CREATE INDEX, so a SEARCH index declared with where= is created over the WHOLE table — it finds the same rows and only costs more space — while a partial UNIQUE one is refused, because widening it would forbid duplicates the domain allows. If you need the partial uniqueness on this engine, enforce it with a generated column plus a plain UNIQUE over it, which is the one MySQL idiom that expresses the same rule"
        ),
        Engine.SQLITE: Full(),
    },
    Cap.DROP_COLUMN_CASCADES_FK: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Nope(
            "dropping a column that a foreign key still holds answers error 1553: InnoDB needs the index the key sits on. The key has to be dropped first, in its own operation — declare the `DropForeignKey` before the `DropColumn` and the same migration runs on all three engines"
        ),
        Engine.MYSQL: Nope(
            "dropping a column that a foreign key still holds answers error 1553: InnoDB needs the index the key sits on. The key has to be dropped first, in its own operation — declare the `DropForeignKey` before the `DropColumn` and the same migration runs on all three engines"
        ),
        Engine.SQLITE: Nope(
            "it refuses to drop a column that a foreign key names, and it has no DROP CONSTRAINT to take the key out of the way first: the table has to be rebuilt (create the new one without the column, copy the rows, drop the old one and rename), which is the user's call and goes in an explicit RunSQL"
        ),
    },
    Cap.DECIMAL_ORDERING: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Degraded(
            "a Decimal is stored as TEXT and comes back exact, but ORDER BY and comparisons sort it lexicographically: '9.99' comes after '10.00'"
        ),
    },
    Cap.TIMESTAMPTZ: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Degraded(
            "it has no usable type with a time zone: TIMESTAMP tops out in 2038 and DATETIME is not tz-aware, so a SnakeUtc is stored as ISO-8601 TEXT. The instant comes back whole, but the engine does not treat it as a date when sorting, comparing or operating"
        ),
        Engine.MYSQL: Degraded(
            "it has no usable type with a time zone: TIMESTAMP tops out in 2038 and DATETIME is not tz-aware, so a SnakeUtc is stored as ISO-8601 TEXT. The instant comes back whole, but the engine does not treat it as a date when sorting, comparing or operating"
        ),
        Engine.SQLITE: Degraded(
            "it does not tell timestamptz from timestamp: both are ISO-8601 TEXT, and the time zone travels in the text instead of being something the engine understands"
        ),
    },
    Cap.INTERVAL: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Degraded(
            "it has no interval type: a timedelta is stored as TEXT, so the engine cannot compare it as a duration"
        ),
        Engine.MYSQL: Degraded(
            "it has no interval type: a timedelta is stored as TEXT, so the engine cannot compare it as a duration"
        ),
        Engine.SQLITE: Degraded(
            "it has no interval type: a timedelta is stored as TEXT, so the engine cannot compare it as a duration"
        ),
    },
    Cap.JSON: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Degraded(
            "it has a JSON type, but it ignores the declared backing: there is no JSONB, so storage= changes nothing here"
        ),
        Engine.MYSQL: Degraded(
            "it has a JSON type, but it ignores the declared backing: there is no JSONB, so storage= changes nothing here"
        ),
        Engine.SQLITE: Degraded(
            "JSON is TEXT: the json_* functions operate on it, but there is no type, no validation on write, and no indexes over its keys"
        ),
    },
    Cap.UUID: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),  # native UUID type since 10.7, and it validates: bad input answers 1292
        Engine.MYSQL: Degraded(
            "it has no UUID type: it goes as CHAR(36), with no validation from the engine"
        ),
        Engine.SQLITE: Degraded(
            "a UUID is stored as TEXT, with no type and no validation"
        ),
    },
    Cap.BOOLEAN: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Degraded(
            "it has no boolean: a bool is TINYINT(1), so the engine accepts any one-byte integer there"
        ),
        Engine.MYSQL: Degraded(
            "it has no boolean: a bool is TINYINT(1), so the engine accepts any one-byte integer there"
        ),
        Engine.SQLITE: Degraded(
            "it has no boolean: a bool is stored as 0/1 in an INTEGER"
        ),
    },
    Cap.INT_WIDTHS: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Degraded(
            "it does not tell integer widths apart: SMALLINT, INTEGER and BIGINT are the same INTEGER, so a model that depends on the range does not fail here and does fail on Postgres"
        ),
    },
    Cap.ARRAYS: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Degraded(
            "it has no arrays: a list[T] is stored as JSON in a TEXT column and comes back as the same list, but the engine cannot query INSIDE it"
        ),
        Engine.MYSQL: Degraded(
            "it has no arrays: a list[T] is stored as JSON in a TEXT column and comes back as the same list, but the engine cannot query INSIDE it"
        ),
        Engine.SQLITE: Degraded(
            "it has no arrays: a list[T] is stored as JSON in a TEXT column and comes back as the same list, but the engine cannot query INSIDE it nor index its elements"
        ),
    },
    Cap.FLOAT_SPECIALS: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Degraded(
            "it does not store the floating-point specials: a NaN or an infinity is an error, not a value"
        ),
        Engine.MYSQL: Degraded(
            "it does not store the floating-point specials: a NaN or an infinity is an error, not a value"
        ),
        Engine.SQLITE: Degraded(
            "it does not store the floating-point specials: a NaN float comes back NULL"
        ),
    },
    Cap.CALENDAR_INTERVAL: {
        Engine.POSTGRES: Full(),
        Engine.MARIADB: Full(),
        Engine.MYSQL: Full(),
        Engine.SQLITE: Degraded(
            "months and years OVERFLOW instead of clamping to the end of the month: 2026-01-31 plus one month is 2026-03-03 here and 2026-02-28 on the other two. Days, hours, minutes and seconds are identical everywhere"
        ),
    },
}
"""Every capability against every engine. Incomplete rows do not get past `capabilities_for`."""


def flavour_of(version_string: str) -> Engine | None:
    """Which of the two servers said that, or `None` when it is not recognisable.

    MariaDB writes its name into `SELECT VERSION()` and MySQL does not; Django reads it the same way.
    Anything else answers `None` and not a guess: MySQL is the restrictive one for `RETURNING` and
    the permissive one for `CTE_IN_COMPOUND_BRANCH`, so no flavour is the safe bet both ways.
    """
    if "mariadb" in version_string.lower():
        return Engine.MARIADB
    if version_string[:1].isdigit():
        return Engine.MYSQL
    return None


def _strictest(supports: tuple[Support | Since, ...]) -> Support | Since:
    """The most restrictive of several answers: `Nope` beats `Degraded`, which beats `Full`."""
    for kind in (Nope, Degraded, Since):
        for support in supports:
            if isinstance(support, kind):
                return support
    return supports[0]


def capabilities_for(
    engine: Engine, engine_version: tuple[int, ...] | None = None
) -> SnakeCapabilities:
    """One engine's column, ready for its dialect.

    `engine_version` only matters to a `Since`; the other states ignore it.
    """
    return SnakeCapabilities(
        {cap: row[engine] for cap, row in MATRIX.items()}, engine_version=engine_version
    )


def strictest_of(
    engines: tuple[Engine, ...], engine_version: tuple[int, ...] | None = None
) -> SnakeCapabilities:
    """What ALL of these engines can do, capability by capability.

    The honest answer while the flavour is unknown, and the same one the dialect gave before the two
    had columns — so a dialect built without a connection behaves as it always did.
    """
    return SnakeCapabilities(
        {
            cap: _strictest(tuple(row[e] for e in engines))
            for cap, row in MATRIX.items()
        },
        engine_version=engine_version,
    )
