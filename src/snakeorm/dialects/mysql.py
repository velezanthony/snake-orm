"""MySQL / MariaDB dialect. It breaks Postgres/SQLite assumptions: no `RETURNING` (the PK comes
through `lastrowid`), upsert with `ON DUPLICATE KEY UPDATE` (on ANY unique key, not a chosen one),
and non-transactional DDL (N steps are not atomic). Identifiers with backticks; literals escape `\\`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import get_args, get_origin
from uuid import UUID

from snakeorm.dialects.literals import numeric_literal
from snakeorm.core.exceptions import SnakeDialectError
from snakeorm.dialects.capabilities import (
    AlterColumnStyle,
    CommentStyle,
    EmptyInsertStyle,
    Cap,
    Degraded,
    DerivedFlags,
    Full,
    Nope,
    SnakeCapabilities,
    SnakeLimits,
    SnakeSyntax,
)
from snakeorm.expressions.scalar import SnakeFunc
from snakeorm.times import SnakeUtc
from snakeorm.metadata.type_params import base_type
from snakeorm.metadata import (
    SnakeDateTimeParams,
    SnakeDecimalParams,
    SnakeIndexMethod,
    SnakeIntParams,
    SnakeIntSize,
    SnakeServerDefault,
    SnakeFloatParams,
    SnakeStrParams,
    SnakeTimeParams,
    SnakeTypeParams,
)

# The ones MySQL puts in when none are asked for. It is NOT 0: a bare `DATETIME` truncates to seconds
# IN SILENCE, and Python's `datetime` carries microseconds. The CEILING is a dialect flag, not a
# constant.
_MYSQL_DEFAULT_FRACTIONAL = 6

# An integer's width -> its type on MySQL. The canonical one is `INT`, not `INTEGER`.
_MYSQL_INT_SIZES: dict[SnakeIntSize, str] = {
    SnakeIntSize.SMALLINT: "SMALLINT",
    SnakeIntSize.INTEGER: "INT",
    SnakeIntSize.BIGINT: "BIGINT",
}

# Scalar function (agnostic) -> MySQL. DATE_TRUNC is not here: MySQL does not have it, asking for it fails clearly.
_MYSQL_FUNCTIONS: dict[SnakeFunc, str] = {
    SnakeFunc.LOWER: "LOWER",
    SnakeFunc.UPPER: "UPPER",
    SnakeFunc.TRIM: "TRIM",
    SnakeFunc.LENGTH: "CHAR_LENGTH",  # LENGTH counts BYTES on MySQL; CHAR_LENGTH counts characters
    SnakeFunc.CONCAT: "CONCAT",
    SnakeFunc.EXTRACT: "EXTRACT",
    SnakeFunc.ABS: "ABS",
    SnakeFunc.ROUND: "ROUND",
    SnakeFunc.SUBSTRING: "SUBSTRING",
    SnakeFunc.REPLACE: "REPLACE",
    SnakeFunc.CEIL: "CEIL",
    SnakeFunc.FLOOR: "FLOOR",
    SnakeFunc.SQRT: "SQRT",
    SnakeFunc.POWER: "POWER",
}

# BTREE is the default (implicit). HASH gets translated; GIN/GIST/BRIN are Postgres's and fail clearly.
_MYSQL_INDEX_METHODS: dict[SnakeIndexMethod, str] = {
    SnakeIndexMethod.HASH: "HASH",
}


_MYSQL_CANNOT: dict[SnakeFunc, str] = {
    SnakeFunc.DATE_TRUNC: "MySQL has no DATE_TRUNC.",
}
"""What the engine genuinely cannot do, and why.

Declared rather than left out: a function missing from the table above reads exactly like one
nobody got round to, and silence meaning two different things is how `ABS` and `ROUND` sat absent
from SQLite while the other two had both.
"""

_missing = set(SnakeFunc) - set(_MYSQL_FUNCTIONS) - set(_MYSQL_CANNOT)
if (
    _missing
):  # pragma: no cover - the guard exists so this can never be reached in a good build
    raise SnakeDialectError(
        "MySQLDialect does not answer for every scalar function: "
        f"{sorted(f.name for f in _missing)}. Add it to _MYSQL_FUNCTIONS, or to _MYSQL_CANNOT "
        "with the reason. Like the `Cap` catalogue, forgetting one fails at import."
    )

_MYSQL_SERVER_DEFAULTS: dict[SnakeServerDefault, str] = {
    SnakeServerDefault.NOW: "CURRENT_TIMESTAMP",
    SnakeServerDefault.UUID_V4: "(UUID())",  # MySQL 8: an expression, in parentheses inside a DEFAULT
    SnakeServerDefault.TRUE: "1",  # MySQL has no boolean: TINYINT(1)
    SnakeServerDefault.FALSE: "0",
    SnakeServerDefault.ZERO: "0",
}

# Default Python type -> MySQL type mapping. `int` and `dict` are NOT here: they depend on a knob
# (`int_size`, `json_storage`) and `map_type` resolves them.
_MYSQL_TYPES: dict[object, str] = {
    str: "TEXT",
    bool: "TINYINT(1)",  # MySQL has no native BOOLEAN: it is an alias of TINYINT(1)
    float: "DOUBLE",
    # `Decimal` is NOT here, for the same reason as `datetime`, `int` and `dict`: its type depends
    # on the declared parameters and `map_type` resolves it. A bare `DECIMAL` in this table WAS the
    # bug — MySQL reads it as `DECIMAL(10,0)`, so `9.99` came back `10`. The table won before anyone
    # had looked at the model, and what it won was somebody's money.
    bytes: "LONGBLOB",  # BLOB tops out at 64KB; LONGBLOB for arbitrary bytes, like PG's BYTEA
    date: "DATE",
    # `datetime` is NOT here, same as `int` and `dict`: its type depends on the declared precision
    # and `_datetime_type` resolves it. Having it here with the `(6)` baked in was what made the
    # declared precision get lost — the table won before anyone had looked at it.
    time: "TIME(6)",
    UUID: "CHAR(36)",  # MySQL has no native UUID: the canonical 36-character form
    # timedelta is NOT here: MySQL has no interval type. It is rejected in map_type, not faked.
}


def _element_type(annotation: object) -> object:
    """The element type of a `list[...]`; it fails clearly if the list does not declare it."""
    args = get_args(annotation)
    if not args:
        raise SnakeDialectError(f"{annotation!r} does not declare its element type.")
    return args[0]


class MySQLDialect(DerivedFlags):
    """How the SQL is written for MySQL/MariaDB (PyMySQL driver).

    Placeholder `%s` (paramstyle `format`); it depends on the driver, but the common ones agree.
    """

    capabilities = SnakeCapabilities(
        {
            # What it does, and does well.
            Cap.ROW_CONSTRUCTOR: Full(),  # `(a, b) IN ((1, 2), (3, 4))` works
            Cap.UPSERT: Full(),  # ON DUPLICATE KEY UPDATE
            Cap.ADD_CONSTRAINT: Full(),  # ALTER TABLE ... ADD CONSTRAINT / ADD FOREIGN KEY
            Cap.ALTER_COLUMN: Full(),  # MODIFY COLUMN / CHANGE COLUMN
            Cap.ROW_LOCKING: Full(),  # SELECT ... FOR UPDATE
            Cap.SET_ISOLATION: Full(),  # SET TRANSACTION ISOLATION LEVEL
            Cap.TEXT_IN_PRIMARY_KEY: Nope(
                "a key needs a length and TEXT has none, so it answers error 1170 and the whole "
                "CREATE TABLE dies. Give the column a `max_length` and it becomes a VARCHAR"
            ),
            Cap.REPLACE_VIEW: Full(),  # CREATE OR REPLACE VIEW
            Cap.PARENTHESISED_COMPOUND: Full(),  # (SELECT ...) UNION (SELECT ...)
            Cap.DECIMAL_ORDERING: Full(),  # a real DECIMAL, sorts as a number
            Cap.INT_WIDTHS: Full(),  # TINYINT/SMALLINT/INT/BIGINT are different
            # What it does NOT do.
            Cap.CTE_IN_COMPOUND_BRANCH: Nope(
                "it does not accept a WITH RECURSIVE as a branch of a UNION/EXCEPT/INTERSECT "
                "(error 1064) even though it parenthesises branches perfectly well, so a "
                "recursion cannot be composed with a set operation: run it on its own"
            ),
            Cap.RETURNING: Nope(
                "it has no RETURNING: the autoincrement PK is recovered with lastrowid, so a "
                "write that needs the returned rows makes one extra round trip"
            ),
            Cap.TRANSACTIONAL_DDL: Nope(
                "DDL commits implicitly: an N-step migration is NOT all-or-nothing, and if step "
                "3 fails, the first two are already applied"
            ),
            Cap.SCHEMAS: Nope(
                "it has no named schemas: in MySQL a 'schema' IS a database, not a namespace "
                "inside one"
            ),
            # MEASURED. This ONE dialect serves TWO engines that disagree, and the ORM's
            # idempotency rests on the half they disagree about:
            #
            #     CREATE OR REPLACE FUNCTION      MariaDB 11.8  ->  works, and replaces
            #                                     MySQL 8.4     ->  ERROR 1064, syntax error
            #
            # `AlterFunction` re-emits the body to replace a routine, so on MySQL a changed routine
            # would fail where on MariaDB it succeeds — one dialect cannot answer `Full()` for both.
            # The ORM's own side is fine: `emit_create_function` hands the `body` through untouched
            # without asking the dialect anything. Supporting MySQL means a DROP-then-CREATE
            # strategy, which is a decision about migrations rather than missing syntax.
            Cap.STORED_FUNCTIONS: Nope(
                "a routine's body is raw SQL and replacing one relies on CREATE OR REPLACE "
                "FUNCTION, which MariaDB accepts and MySQL rejects outright. This dialect serves "
                "both, so it cannot promise what only one of them does"
            ),
            Cap.ILIKE: Degraded(
                "it has no ILIKE, so the case-insensitive match is written LOWER(a) LIKE LOWER(b): "
                "it matches, and what it folds is whatever the column's collation folds, which is "
                "a decision of the schema and not of the query"
            ),
            # Measured against MariaDB 11.8: `CREATE INDEX ... WHERE` answers ERROR 1064, a raw
            # syntax error, because the clause is not in the grammar at all. Neither MySQL 8 nor
            # MariaDB has partial indexes.
            # Measured against MariaDB 11.8.8: dropping a column a foreign key still holds answers
            # ERROR 1553, "Cannot drop index 'fk_x': needed in a foreign key constraint". InnoDB
            # puts every FK on an index and refuses to lose it while the key is standing. The same
            # server takes the two statements in a row without a complaint, so nothing is lost —
            # what changes is that the constraint has to be named, and the plan says so.
            Cap.DROP_COLUMN_CASCADES_FK: Nope(
                "dropping a column that a foreign key still holds answers error 1553: InnoDB "
                "needs the index the key sits on. The key has to be dropped first, in its own "
                "operation — declare the `DropForeignKey` before the `DropColumn` and the same "
                "migration runs on all three engines"
            ),
            Cap.PARTIAL_INDEXES: Nope(
                "it has no partial indexes: WHERE is not part of its CREATE INDEX, so a SEARCH "
                "index declared with where= is created over the WHOLE table — it finds the same "
                "rows and only costs more space — while a partial UNIQUE one is refused, because "
                "widening it would forbid duplicates the domain allows. If you need the partial "
                "uniqueness on this engine, enforce it with a generated column plus a plain UNIQUE "
                "over it, which is the one MySQL idiom that expresses the same rule"
            ),
            Cap.TIMESTAMPTZ: Degraded(
                "it has no usable type with a time zone: TIMESTAMP tops out in 2038 and DATETIME "
                "is not tz-aware, so a SnakeUtc is stored as ISO-8601 TEXT. The instant comes back "
                "whole, but the engine does not treat it as a date when sorting, comparing or "
                "operating"
            ),
            Cap.INTERVAL: Degraded(
                "it has no interval type: a timedelta is stored as TEXT, so the engine cannot "
                "compare it as a duration"
            ),
            # Measured: `DATE_ADD('2026-01-31', INTERVAL 1 MONTH)` is `2026-02-28`, the same as
            # PostgreSQL. It clamps, so there is nothing to warn about.
            Cap.CALENDAR_INTERVAL: Full(),
            Cap.ARRAYS: Degraded(
                "it has no arrays: a list[T] is stored as JSON in a TEXT column and comes back as "
                "the same list, but the engine cannot query INSIDE it"
            ),
            # Measured against MariaDB 11.8.8. The GRAMMAR has no COMMENT ON, but the feature is
            # there:
            #
            #     CREATE TABLE t (c INT COMMENT 'x') COMMENT = 'y'  ->  accepted, both readable
            #     ALTER TABLE t COMMENT = 'z'                       ->  accepted, replaces it
            #     COMMENT ON TABLE t IS 'z'                         ->  ERROR 1064
            #
            # It is `Degraded` and not `Full` because of the COLUMN half. There is no statement that
            # changes a column's comment on its own —`ALTER COLUMN c COMMENT` is a 1064 and `MODIFY
            # COLUMN c COMMENT` is error 4161— so the only spelling rewrites the whole definition,
            # and everything it does not respell is destroyed: measured, the naive shape turned a
            # `NOT NULL DEFAULT 7` into `DEFAULT NULL` and dropped an `AUTO_INCREMENT` in silence.
            # The emitter respells from the metadata, so nothing the MODEL knows is lost; what the
            # DATABASE holds and the model does not describe is. `Degraded` and not `Nope` because
            # this dialect's own introspector already READS both back out of `information_schema`
            # (`COLUMN_COMMENT` and `TABLE_COMMENT`): the round trip works, the rewrite is the cost.
            Cap.COMMENTS: Degraded(
                "it has no COMMENT ON: a table comment is a clause (CREATE TABLE ... COMMENT =, "
                "ALTER TABLE ... COMMENT =) and a COLUMN comment can only change by rewriting the "
                "whole column with MODIFY COLUMN. The definition is respelled from the model, so "
                "what the model declares survives; anything the database holds that the model does "
                "not describe (a collation, ON UPDATE CURRENT_TIMESTAMP, a generated expression) "
                "does not. An empty comment and no comment are also the same value here"
            ),
            # What it does halfway.
            Cap.JSON: Degraded(
                "it has a JSON type, but it ignores the declared backing: there is no JSONB, so "
                "storage= changes nothing here"
            ),
            Cap.UUID: Degraded(
                "it has no UUID type: it goes as CHAR(36), with no validation from the engine"
            ),
            Cap.BOOLEAN: Degraded(
                "it has no boolean: a bool is TINYINT(1), so the engine accepts any one-byte "
                "integer there"
            ),
            Cap.INDEX_METHODS: Degraded(
                "it has USING BTREE and HASH, but not the Postgres methods (GIN, GIST, BRIN)"
            ),
            Cap.FLOAT_SPECIALS: Degraded(
                "it does not store the floating-point specials: a NaN or an infinity is an "
                "error, not a value"
            ),
        }
    )

    syntax = SnakeSyntax(
        triggers_are_table_scoped=False,  # `DROP TRIGGER name`, without `ON table`
        indexes_are_table_scoped=True,  # `DROP INDEX name ON table`
        empty_insert_style=EmptyInsertStyle.EMPTY_ROW,
        alter_column_style=AlterColumnStyle.MYSQL_MODIFY,
        comment_style=CommentStyle.INLINE,  # a CLAUSE (`COMMENT = 'x'`), never a statement
    )

    # Ceilings of the declared parameters, WAY below Postgres's. The scale is a SEPARATE ceiling and
    # a lower one than the precision: `DECIMAL(40,35)` has one valid half and one impossible half.
    limits = SnakeLimits(
        bind_params=65535,  # ceiling of placeholders per prepared statement
        numeric_precision=65,
        numeric_scale=30,
        fractional_seconds=6,
    )

    def __init__(self) -> None:
        # A PER-INSTANCE copy of the type table: `register_type` writes here, not into the module's
        # dict. Global, importing a library that registers a type would sneak it into every dialect
        # in the process, including those of a database that does not support it.
        self._types: dict[object, str] = dict(_MYSQL_TYPES)

    def drop_all_sql(self, tables: Sequence[str]) -> tuple[str, ...]:
        """The drops bracketed by the FK switch: MySQL refuses to drop a referenced table.

        There is no `CASCADE` for a `DROP TABLE` here, and dropping in dependency order would mean
        computing one — for a command whose whole point is that nothing survives. The switch is the
        idiom MySQL itself documents, and it is put BACK: a session left with the checks off accepts
        orphan rows in silence, which is a worse state than the one being repaired.
        """
        if not tables:
            return ()
        drops = tuple(
            f"DROP TABLE IF EXISTS {self.quote_ident(table)}" for table in tables
        )
        return ("SET FOREIGN_KEY_CHECKS = 0", *drops, "SET FOREIGN_KEY_CHECKS = 1")

    def explain_sql(self, sql: str) -> str:
        """`EXPLAIN <statement>`: about a dozen columns per row, and that is the engine's shape."""
        return f"EXPLAIN {sql}"

    def statement_timeout_sql(self, milliseconds: int) -> str | None:
        """MariaDB's `max_statement_time`, converted to the SECONDS it expects.

        THE FORK, and it decides what this line can be: MySQL and MariaDB do not share this
        variable and neither accepts the other's. MariaDB has `max_statement_time` in seconds;
        Oracle's MySQL has `max_execution_time` in milliseconds. One dialect, two spellings, no
        overlap — and nothing in this ORM tells the two forks apart.

        It emits MariaDB's, which is the fork the project tests against. On the other one the server
        refuses by name (`1193 Unknown system variable`) the moment the driver is wrapped: loud, at
        startup, and fixable — not a timeout that quietly never fires.

        The conversion is the point of doing this here. Handing `max_statement_time` a value in
        milliseconds would not fail; it would set a limit a THOUSAND times longer than asked for,
        which is the kind of bug that only surfaces the day something hangs.
        """
        return f"SET SESSION max_statement_time = {milliseconds / 1000:g}"

    def register_type(self, python_type: object, sql_type: str) -> None:
        """Adds (or rewrites) the SQL spelling of a Python type in THIS dialect.

        See `SnakeDialect.register_type`. It goes per dialect because the same Python type is
        written differently on each engine: an `Inet` is `INET` on Postgres and `TEXT` here.
        """
        self._types[python_type] = sql_type

    def placeholder(self, index: int) -> str:
        """PyMySQL uses a positional `%s` (paramstyle `format`); the index is not needed."""
        return "%s"

    def trigger_statements(self, name: str, body: str) -> tuple[list[str], str]:
        """The body goes bare. MySQL accepts a single statement without `BEGIN`/`END`.

        Several statements WOULD need them, and would also need the client delimiter changed, which
        is a property of the client and not of the SQL. A body of one statement is what this ORM
        emits, so that door stays closed until something needs it opened.
        """
        return [], body

    def quote_ident(self, name: str) -> str:
        """Quotes with BACKTICKS and doubles the inner backticks (MySQL's equivalent of the quoting)."""
        escaped = name.replace("`", "``")
        return f"`{escaped}`"

    def json_get_sql(
        self, source: str, key_path: tuple[str, ...], as_type: type
    ) -> str:
        """`JSON_EXTRACT` with a `$.a.b` path, UNQUOTED before the cast.

        The unquote is the step that is easy to leave out and impossible to notice: `JSON_EXTRACT`
        returns a JSON scalar, so a string arrives with its quotes still on and `= 'ada'` never
        matches. MySQL's cast targets are its own (`SIGNED`, not `integer`), which is the reason this
        method exists per dialect at all.
        """
        path = "$." + ".".join(key_path)
        access = f"JSON_UNQUOTE(JSON_EXTRACT({source}, '{path}'))"
        cast = _MYSQL_CAST.get(as_type)
        return access if cast is None else f"CAST({access} AS {cast})"

    def date_shift_sql(
        self, source: str, amount_placeholder: str, unit: str, keeps_time: bool
    ) -> str:
        """`DATE_ADD(col, INTERVAL %s DAY)`: the unit is a bare KEYWORD, not a string.

        Measured to take the amount as a prepared parameter and to accept a negative one, which is
        what lets subtraction be the same node with the sign flipped. `keeps_time` is unused: MySQL
        has real date and datetime types.
        """
        return f"DATE_ADD({source}, INTERVAL {amount_placeholder} {unit.upper()})"

    def string_agg_sql(
        self, value: str, separator: str, order_by: str, params: list[object]
    ) -> str:
        """`GROUP_CONCAT(col ORDER BY ... SEPARATOR ', ')`: here the separator is SYNTAX.

        Measured, a placeholder after `SEPARATOR` is a syntax error, so this is the one engine where
        the string reaches the statement. It goes through `literal()` — the same escaping every DDL
        default already uses — which doubles the quote and escapes the backslash. `params` is left
        untouched on purpose, and a test pins that it is.
        """
        clauses = f" ORDER BY {order_by}" if order_by else ""
        return f"GROUP_CONCAT({value}{clauses} SEPARATOR {self.literal(separator)})"

    def integer_division_op(self) -> str:
        """`DIV`, and this is the whole reason the method exists.

        MEASURED: `SELECT 45/50` answers `0.9000` here —type `decimal(6,4)`— while the other two
        answer `0`. MySQL's `/` IS decimal division; `DIV` is the integer one. Emitting `/` for two
        integer columns made `SnakeArith[int]` a lie on this engine and only on this engine.
        """
        return "DIV"

    def cast_sql(self, source: str, as_type: type) -> str:
        """`CAST(x AS DOUBLE)`, and DOUBLE rather than DECIMAL on purpose.

        MEASURED: a bare `CAST(x AS DECIMAL)` is `DECIMAL(10,0)` — no decimal places at all — so it
        would read as a float cast and truncate. The table this reads already says DOUBLE.
        """
        return f"CAST({source} AS {_MYSQL_CAST[as_type]})"

    def _guard_numeric(self, params: SnakeDecimalParams) -> None:
        """Checks that the declared DECIMAL fits within what MySQL accepts.

        They are TWO different ceilings, not one: 65 total digits and 30 decimal places. With a
        single number, a `DECIMAL(40,35)` would pass —the precision is valid— and blow up on the
        engine.
        """
        assert self.max_numeric_precision is not None
        assert self.max_numeric_scale is not None
        if params.precision > self.max_numeric_precision:
            raise SnakeDialectError(
                f"MySQL does not accept more than {self.max_numeric_precision} digits in a "
                f"DECIMAL, and {params.precision} were requested. Postgres goes up to 1000, so "
                f"this model is not portable as it stands: lower the precision or stay on Postgres."
            )
        if params.scale is not None and params.scale > self.max_numeric_scale:
            raise SnakeDialectError(
                f"MySQL does not accept more than {self.max_numeric_scale} decimal places in a "
                f"DECIMAL, and {params.scale} were requested. The ceiling on decimal places is "
                f"lower than the one on total digits ({self.max_numeric_precision}): they are two "
                f"different limits."
            )

    def _datetime_type(self, python_type: type, params: SnakeTypeParams | None) -> str:
        """The `DATETIME(n)` of a date column, or the reasoned refusal if there is nowhere to put it.

        MySQL has no usable type with a time zone. `TIMESTAMP` does store the instant, but it tops
        out in 2038, so the ORM uses `DATETIME`, which stores a wall clock and does NOT preserve the
        instant across zones. That is why `SnakeUtc` —whose whole deal is precisely that, storing an
        instant— does not fit in a `DATETIME`: it would satisfy the signature and break the promise,
        in silence and only once somebody crossed a zone.

        It used to be REJECTED, and with that the same model did not work on all three engines. Now
        it falls back to ISO-8601 TEXT, which preserves the WHOLE instant —time zone included, and
        with no 2038 ceiling—, and the degradation is declared in `capabilities`: what is lost is
        the engine treating it as a date when sorting and comparing, and the session warns about
        that at startup.
        """
        if issubclass(python_type, SnakeUtc):
            return "TEXT"
        registered = self._types.get(python_type)
        if registered is not None:
            return registered  # a registered subclass of your own beats the default
        digits = params.precision if isinstance(params, SnakeDateTimeParams) else None
        if digits is None:
            digits = _MYSQL_DEFAULT_FRACTIONAL
        assert self.max_fractional_seconds is not None
        if digits > self.max_fractional_seconds:
            raise SnakeDialectError(
                f"MySQL does not store more than {self.max_fractional_seconds} fractional-second "
                f"digits, and {digits} were requested. With {self.max_fractional_seconds} you "
                f"already reach microseconds, which is the whole resolution of Python's datetime."
            )
        return f"DATETIME({digits})"

    def map_type(
        self,
        python_type: object,
        autoincrement: bool = False,
        params: SnakeTypeParams | None = None,
    ) -> str:
        """Translates the Python type into the COMPLETE MySQL type. With autoincrement it adds `AUTO_INCREMENT`.

        It honours the integer's width, the text's length, the NUMERIC's precision and the date's.
        It ignores the JSON backing: MySQL only has `JSON` and does not distinguish JSONB, so the
        knob has nothing to translate into (and it is not pretended otherwise).
        """
        if python_type is int:
            size = (
                params.size
                if isinstance(params, SnakeIntParams)
                else SnakeIntSize.BIGINT
            )
            base = _MYSQL_INT_SIZES[size]
            # AUTO_INCREMENT on top of the integer type; the column must be a key (the CREATE TABLE's PK gives that).
            return f"{base} AUTO_INCREMENT" if autoincrement else base
        if python_type is str:
            text = params if isinstance(params, SnakeStrParams) else None
            if text is None or text.max_length is None:
                return "TEXT"
            # CHAR(n) is a FIXED length: it pads with spaces and compares ignoring them.
            return (
                f"CHAR({text.max_length})"
                if text.fixed
                else f"VARCHAR({text.max_length})"
            )
        if python_type is float and isinstance(params, SnakeFloatParams):
            # FLOAT is single precision on MySQL and DOUBLE is double, just like REAL/DOUBLE
            # PRECISION on Postgres but under other names: that is why the translation lives in the
            # dialect.
            return "FLOAT" if params.size == 4 else self._types[float]
        if python_type is time and isinstance(params, SnakeTimeParams):
            # MySQL has no TIMETZ: a time with a zone falls back to TEXT, which keeps the zone in the
            # ISO string. A plain TIME would have thrown it away in silence, satisfying the
            # signature and breaking the deal.
            return "TEXT" if params.with_timezone else self._types[time]
        # `base_type`: a `dict[str, object]` IS a dict column. Comparing the annotation
        # itself let a parameterised one fall through to the default type, so the column
        # came out TEXT and the JSON storage the user asked for was silently dropped.
        if base_type(python_type) is dict:
            return "JSON"  # MySQL 5.7+; it does not distinguish JSONB from JSON
        if isinstance(python_type, type) and issubclass(python_type, datetime):
            return self._datetime_type(python_type, params)
        if isinstance(params, SnakeDecimalParams):
            self._guard_numeric(params)
            scale = f",{params.scale}" if params.scale is not None else ""
            return f"DECIMAL({params.precision}{scale})"
        if python_type is Decimal:
            # Undeclared precision. Postgres maps this to an unbounded NUMERIC and loses nothing, so
            # the model is only lossy HERE: MySQL has no unbounded decimal, and a bare `DECIMAL` is
            # `DECIMAL(10,0)` — every fractional digit gone, silently. This is not a query
            # capability that `Degraded` could cover; what is lost is the VALUE, so the plan stops.
            raise SnakeDialectError(
                "MySQL has no unbounded DECIMAL: a column of type Decimal must declare its "
                "precision with snake_decimal(precision=..., scale=...). Without it the engine "
                "uses DECIMAL(10,0) and rounds every value to an integer — 9.99 is stored as 10. "
                "Postgres accepts this model because its NUMERIC is arbitrary precision, which is "
                "why the same code is lossless there and lossy here."
            )
        origin = get_origin(python_type)
        if origin is list or python_type is list:
            # MySQL has no arrays: the list falls back to TEXT and travels as JSON (`adapt_param`
            # serialises it, `_to_list` rebuilds it). Declared `Degraded`, because what is lost is
            # being able to query INSIDE the array from SQL.
            return "TEXT"
        if python_type is timedelta:
            # No interval type: TEXT with the `str(timedelta)` that `adapt_param` already writes. It
            # used to fall through to the generic message at the end, which said it did not know how
            # to map it and did not say what to do; it was the only type neither supported nor
            # rejected with a reason.
            return "TEXT"
        try:
            return self._types[python_type]
        except (KeyError, TypeError):
            raise SnakeDialectError(
                f"MySQLDialect does not know how to map {python_type!r} to a SQL type"
            ) from None

    def limit_offset(
        self, limit: int | None, offset: int | None, params: list[object]
    ) -> str:
        """A parametrised `LIMIT %s OFFSET %s`. MySQL demands a LIMIT whenever there is an OFFSET, so
        a bare OFFSET carries a huge LIMIT (MySQL's standard idiom for "everything from N on")."""
        parts: list[str] = []
        if limit is not None:
            params.append(limit)
            parts.append(f"LIMIT {self.placeholder(len(params))}")
        elif offset is not None:
            parts.append(
                "LIMIT 18446744073709551615"
            )  # 2^64-1: "no limit" with an OFFSET, MySQL style
        if offset is not None:
            params.append(offset)
            parts.append(f"OFFSET {self.placeholder(len(params))}")
        return " ".join(parts)

    def on_conflict_clause(
        self, conflict_columns: Sequence[str], update_columns: Sequence[str]
    ) -> str:
        """`ON DUPLICATE KEY UPDATE`: MySQL's upsert, which fires on ANY unique key.
        No conflict columns; for "do nothing" (MySQL has no `DO NOTHING`) it uses `col = col`.
        """
        if not update_columns:
            col = self.quote_ident(conflict_columns[0])
            return f"ON DUPLICATE KEY UPDATE {col} = {col}"
        assignments = ", ".join(
            f"{self.quote_ident(column)} = VALUES({self.quote_ident(column)})"
            for column in update_columns
        )
        return f"ON DUPLICATE KEY UPDATE {assignments}"

    def literal(self, value: object) -> str:
        """Formats a default value as a MySQL SQL literal (DDL DEFAULT).
        MySQL interprets the BACKSLASH in strings, so it is escaped as well as the quote; a bool goes as 1/0.
        """
        if isinstance(value, Enum):
            value = value.value
        if value is None:
            return "NULL"
        if isinstance(value, bool):  # before int: bool is a subclass of int
            return "1" if value else "0"
        if isinstance(value, (int, float, Decimal)):
            return numeric_literal(value, "MySQLDialect")
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace("'", "''")
            return f"'{escaped}'"
        raise SnakeDialectError(
            f"MySQLDialect does not know how to format {value!r} as a SQL literal"
        )

    def function_name(self, func: SnakeFunc) -> str:
        """Translates the agnostic name of a scalar function into MySQL's own."""
        if func in _MYSQL_FUNCTIONS:
            return _MYSQL_FUNCTIONS[func]
        reason = _MYSQL_CANNOT.get(func)
        if reason is None:
            # Not a catalogue member at all. A real one cannot reach here: the import
            # guard above refuses to load a dialect that skipped any.
            raise SnakeDialectError(
                f"MySQLDialect does not know how to translate the function {func!r}"
            )
        raise SnakeDialectError(
            f"MySQLDialect cannot translate {func.name}: {reason} "
            "Reach for it through `raw()` with the engine's own spelling."
        )

    def index_method(self, method: SnakeIndexMethod) -> str:
        """Translates the index method (agnostic) into MySQL's jargon for the `USING`."""
        try:
            return _MYSQL_INDEX_METHODS[method]
        except KeyError:
            raise SnakeDialectError(
                f"MySQLDialect does not know how to translate the index method {method!r} (GIN/GIST/BRIN are Postgres ones)"
            ) from None

    def server_default_sql(self, value: SnakeServerDefault) -> str:
        """Translates the server-side default (agnostic) into its MySQL SQL expression."""
        try:
            return _MYSQL_SERVER_DEFAULTS[value]
        except KeyError:
            raise SnakeDialectError(
                f"MySQLDialect does not know how to translate the server_default {value!r}"
            ) from None


_MYSQL_CAST = {int: "SIGNED", float: "DOUBLE", bool: "SIGNED"}
"""What a declared type becomes in a MySQL cast. Its targets are its own —`SIGNED`, not
`integer`— which is exactly why the emission lives in the dialect."""
