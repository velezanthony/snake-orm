"""How the SQL is written for SQLite. It supports almost all of `query/` (RETURNING, ON CONFLICT,
row constructor, WITH RECURSIVE, window functions).

What it does NOT have, and what it has only HALFWAY, is declared in `capabilities`: the absences
(`ADD CONSTRAINT`, `ALTER COLUMN`, `CREATE SCHEMA`, `FOR UPDATE`, `COMMENT ON`) fail at COMPILE time
with the alternative —SQL the engine would not understand is never emitted—, and the degradations (a
`Decimal` that comes back exact but sorts as text) are warned about when the session opens, once
each.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import get_origin
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
from snakeorm.times import SnakeUtc
from snakeorm.expressions import SnakeFunc
from snakeorm.metadata import (
    SnakeIndexMethod,
    SnakeServerDefault,
    SnakeTypeParams,
)

_SQLITE_TYPES: dict[object, str] = {
    SnakeUtc: "TEXT",
    # SQLite has FIVE storage classes; everything lands in one. The engine tells nothing else apart.
    int: "INTEGER",
    bool: "INTEGER",  # 0/1: SQLite has no boolean
    str: "TEXT",
    float: "REAL",
    bytes: "BLOB",
    # TEXT, not NUMERIC: the NUMERIC affinity converts any numeric text to REAL, destroying the
    # exactness Decimal exists to preserve. With TEXT it comes back exact.
    Decimal: "TEXT",
    # No date types: ISO-8601 text, the only thing that sorts and compares properly (SQLite recommends it).
    datetime: "TEXT",
    date: "TEXT",
    time: "TEXT",
    timedelta: "TEXT",
    UUID: "TEXT",
    dict: "TEXT",  # JSON as text: SQLite's json_* functions operate on TEXT
}

_SQLITE_FUNCTIONS: dict[SnakeFunc, str] = {
    SnakeFunc.LOWER: "LOWER",
    SnakeFunc.UPPER: "UPPER",
    SnakeFunc.TRIM: "TRIM",
    SnakeFunc.LENGTH: "LENGTH",
    SnakeFunc.CONCAT: "CONCAT",
    SnakeFunc.SUBSTRING: "SUBSTRING",
    SnakeFunc.REPLACE: "REPLACE",
    SnakeFunc.ABS: "ABS",
    SnakeFunc.ROUND: "ROUND",
    # `CEIL`, `FLOOR`, `SQRT` and `POWER` are a COMPILE-TIME option (`ENABLE_MATH_FUNCTIONS`); a
    # build without it answers `no such function: ceil` at runtime. That is a property of the
    # BINARY, not of "SQLite", so it cannot be a `Cap`: a capability is answered by the class, which
    # knows nothing about which library got linked. `ABS` and `ROUND` are NOT in that group — every
    # build ships them, which is why their absence here was a bug and not a limit.
    SnakeFunc.CEIL: "CEIL",
    SnakeFunc.FLOOR: "FLOOR",
    SnakeFunc.SQRT: "SQRT",
    SnakeFunc.POWER: "POWER",
}

_SQLITE_CANNOT: dict[SnakeFunc, str] = {
    SnakeFunc.DATE_TRUNC: "SQLite has no DATE_TRUNC.",
    SnakeFunc.EXTRACT: "SQLite has no EXTRACT.",
}
"""What the engine genuinely cannot do, and why.

Declared rather than left out, because a function missing from the table above reads exactly like
one nobody got round to. That is how `ABS` and `ROUND` sat absent while Postgres and MySQL had both:
silence meant two different things and nothing could tell them apart.
"""

_missing = set(SnakeFunc) - set(_SQLITE_FUNCTIONS) - set(_SQLITE_CANNOT)
if (
    _missing
):  # pragma: no cover - the guard exists so this can never be reached in a good build
    raise SnakeDialectError(
        "SQLiteDialect does not answer for every scalar function: "
        f"{sorted(f.name for f in _missing)}. Add it to _SQLITE_FUNCTIONS, or to _SQLITE_CANNOT "
        "with the reason. Like the `Cap` catalogue, forgetting one fails at import."
    )

_SQLITE_SERVER_DEFAULTS: dict[SnakeServerDefault, str] = {
    SnakeServerDefault.NOW: "CURRENT_TIMESTAMP",
}


class SQLiteDialect(DerivedFlags):
    """How the SQL is written for SQLite (with the stdlib's `sqlite3` driver)."""

    capabilities = SnakeCapabilities(
        {
            # What it does, and does well.
            Cap.RETURNING: Full(),  # since 3.35
            Cap.ROW_CONSTRUCTOR: Full(),  # `(a, b) IN ((1, 2))` works
            Cap.TRANSACTIONAL_DDL: Full(),  # DDL goes inside the transaction
            Cap.UPSERT: Full(),  # ON CONFLICT since 3.24
            # `CREATE INDEX ... WHERE` since 3.8: the small engine has the clause the big MySQL
            # does not, which is why this capability is answered per engine and not assumed from
            # how complete an engine looks.
            Cap.PARTIAL_INDEXES: Full(),
            # What it does NOT do: each one cuts at compile time or changes the migration plan.
            Cap.ADD_CONSTRAINT: Nope(
                "it does not accept ALTER TABLE ... ADD CONSTRAINT: FKs go INSIDE the CREATE "
                "TABLE, so the plan emits them there and orders the tables topologically"
            ),
            Cap.ALTER_COLUMN: Nope(
                "it cannot change the type nor the nullability of an existing column: it would "
                "demand rebuilding the whole table"
            ),
            # Measured on SQLite 3.50.4: `DROP COLUMN` over a column named in a FOREIGN KEY answers
            # "unknown column ... in foreign key definition" and leaves the table untouched. The
            # engine that drops columns since 3.35 does not drop THIS one, and unlike MySQL it has
            # no second statement to offer: with no `DROP CONSTRAINT`, the key cannot go first.
            Cap.DROP_COLUMN_CASCADES_FK: Nope(
                "it refuses to drop a column that a foreign key names, and it has no DROP "
                "CONSTRAINT to take the key out of the way first: the table has to be rebuilt "
                "(create the new one without the column, copy the rows, drop the old one and "
                "rename), which is the user's call and goes in an explicit RunSQL"
            ),
            Cap.SCHEMAS: Nope(
                "it has no named schemas; its 'schemas' are ATTACHED databases (ATTACH)"
            ),
            Cap.STORED_FUNCTIONS: Nope(
                "it does not store functions: SQLite's are registered from the process that "
                "opens the connection, so they do not live in the database and a migration cannot "
                "create them"
            ),
            Cap.ROW_LOCKING: Nope(
                "it cannot lock rows (SELECT ... FOR UPDATE): it locks the whole FILE"
            ),
            Cap.SET_ISOLATION: Nope(
                "it has no SET TRANSACTION ISOLATION LEVEL: one writer at a time makes its "
                "transactions serialisable already, and the only knob it offers, "
                "PRAGMA read_uncommitted, LOWERS the isolation instead of raising it"
            ),
            Cap.TEXT_IN_PRIMARY_KEY: Full(),  # TEXT keys fine here
            Cap.COMMENTS: Nope(
                "it does not store COMMENT ON, so db_comment values are omitted"
            ),
            Cap.REPLACE_VIEW: Nope(
                "it has no CREATE OR REPLACE VIEW: altering a view is emulated with DROP + CREATE"
            ),
            Cap.PARENTHESISED_COMPOUND: Nope(
                "it rejects parentheses in the branches of a UNION/EXCEPT/INTERSECT, so a LIMIT "
                "cannot be confined to one branch"
            ),
            Cap.CTE_IN_COMPOUND_BRANCH: Nope(
                "it does not accept a WITH RECURSIVE as a branch of a UNION/EXCEPT/INTERSECT "
                '(near "WITH": syntax error), so a recursion cannot be composed with a set '
                "operation: run it on its own"
            ),
            Cap.ILIKE: Degraded(
                "it has no ILIKE: the case-insensitive match is written LOWER(a) LIKE LOWER(b), "
                "which matches and folds only ASCII"
            ),
            Cap.INDEX_METHODS: Nope(
                "it has only one kind of index, so it does not accept method= (GIN, GIST...)"
            ),
            Cap.ARRAYS: Degraded(
                "it has no arrays: a list[T] is stored as JSON in a TEXT column and comes back "
                "as the same list, but the engine cannot query INSIDE it nor index its elements"
            ),
            # What it does halfway: the VALUE goes in and comes out exact, the SQL semantics do not.
            Cap.DECIMAL_ORDERING: Degraded(
                "a Decimal is stored as TEXT and comes back exact, but ORDER BY and comparisons "
                "sort it lexicographically: '9.99' comes after '10.00'"
            ),
            Cap.TIMESTAMPTZ: Degraded(
                "it does not tell timestamptz from timestamp: both are ISO-8601 TEXT, and the "
                "time zone travels in the text instead of being something the engine understands"
            ),
            Cap.INTERVAL: Degraded(
                "it has no interval type: a timedelta is stored as TEXT, so the engine cannot "
                "compare it as a duration"
            ),
            Cap.CALENDAR_INTERVAL: Degraded(
                "months and years OVERFLOW instead of clamping to the end of the month: "
                "2026-01-31 plus one month is 2026-03-03 here and 2026-02-28 on the other two. "
                "Days, hours, minutes and seconds are identical everywhere"
            ),
            Cap.JSON: Degraded(
                "JSON is TEXT: the json_* functions operate on it, but there is no type, no "
                "validation on write, and no indexes over its keys"
            ),
            Cap.UUID: Degraded(
                "a UUID is stored as TEXT, with no type and no validation"
            ),
            Cap.BOOLEAN: Degraded(
                "it has no boolean: a bool is stored as 0/1 in an INTEGER"
            ),
            Cap.INT_WIDTHS: Degraded(
                "it does not tell integer widths apart: SMALLINT, INTEGER and BIGINT are the "
                "same INTEGER, so a model that depends on the range does not fail here and does "
                "fail on Postgres"
            ),
            Cap.FLOAT_SPECIALS: Degraded(
                "it does not store the floating-point specials: a NaN float comes back NULL"
            ),
        }
    )

    syntax = SnakeSyntax(
        # A SQLite trigger is GLOBAL, not per table: `DROP TRIGGER x` without `ON table` (Postgres's
        # shape gave `near "ON": syntax error` and left ORM triggers the ORM could not drop).
        triggers_are_table_scoped=False,
        indexes_are_table_scoped=False,  # `DROP INDEX x`, without `ON table`
        empty_insert_style=EmptyInsertStyle.DEFAULT_VALUES,
        # `NULLS FIRST|LAST` since SQLite 3.30; measured on 3.50.4, which is what this
        # interpreter carries. Not shared with MySQL, which answers 1064 to the same words.
        has_nulls_ordering=True,
        alter_column_style=AlterColumnStyle.UNSUPPORTED,
        # It stores no comment at all, so there is no spelling to pick. Same as the line above: the
        # plan stops on `Cap.COMMENTS` before any emitter runs.
        comment_style=CommentStyle.UNSUPPORTED,
        # MEASURED, and it is not the pragma the design named. `PRAGMA foreign_keys = OFF` is
        # documented as a NO-OP inside a transaction, and `SQLiteDriver` opens one lazily before the
        # first statement — so a rebuild that trusted it would run with the keys still armed and
        # nothing would say so. `defer_foreign_keys` is the one built for this: it is set INSIDE the
        # transaction, it resets itself at COMMIT, and the violations it postpones are reported by
        # that COMMIT.
        defer_constraints_statement="PRAGMA defer_foreign_keys = ON",
    )

    # `None`, and not some big number: SQLite has no ceilings to break because it does NOT STORE the
    # declared parameter —it has a per-column affinity and nothing else—. A number would assert a
    # limit that does not exist; a small one would reject models this engine stores just as well.
    limits = SnakeLimits(
        bind_params=32766,  # the default SQLITE_MAX_VARIABLE_NUMBER since 3.32
        numeric_precision=None,
        numeric_scale=None,
        fractional_seconds=None,
    )

    def __init__(self) -> None:
        # A PER-INSTANCE copy of the type table: `register_type` writes here, not into the module's
        # dict. Global, importing a library that registers a type would sneak it into every dialect
        # in the process, including those of a database that does not support it.
        self._types: dict[object, str] = dict(_SQLITE_TYPES)

    def drop_all_sql(self, tables: Sequence[str]) -> tuple[str, ...]:
        """Plain drops, with the key checking POSTPONED to the COMMIT.

        No `CASCADE`: SQLite does not parse the keyword and answers a syntax error.

        And not `PRAGMA foreign_keys = OFF` either. MEASURED, it makes nothing work: the pragma is a
        no-op inside a transaction — the same finding written twenty lines above, about
        `defer_constraints_statement` — and `SQLiteDriver._ensure_tx` opens one before every
        statement that reaches this engine, so the value still reads 1 immediately after the OFF is
        sent.

        `defer_foreign_keys` is the pragma built for this and the one `syntax` already names: it
        takes effect INSIDE the transaction and moves every check to the COMMIT, by which point
        every table is gone and there is nothing left to violate. That also covers the case no
        ordering can reach — two tables pointing at each other — which is what Postgres's `CASCADE`
        and MySQL's switch survive today. And it resets ITSELF at that COMMIT, so unlike MySQL's
        switch there is nothing to put back: no session is ever handed over with its keys disarmed.

        It is a COMMIT-time promise, so the one thing it asks of the caller is the one thing the
        Protocol already asks: run the batch as it comes. A caller that committed between two drops
        would be back to needing a safe order — which is what `fresh` used to do, and it died here
        with `FOREIGN KEY constraint failed` halfway through, schema half gone, because a model
        declared BEFORE the one pointing at it is perfectly legal.
        """
        if not tables:
            return ()
        drops = tuple(
            f"DROP TABLE IF EXISTS {self.quote_ident(table)}" for table in tables
        )
        defer = self.syntax.defer_constraints_statement
        return ((defer,) if defer is not None else ()) + drops

    def explain_sql(self, sql: str) -> str:
        """`EXPLAIN QUERY PLAN`, and the two words matter.

        A bare `EXPLAIN` here dumps the VDBE bytecode — a real answer to a different question, and
        the one a user reading "explain" never wants.
        """
        return f"EXPLAIN QUERY PLAN {sql}"

    def statement_timeout_sql(self, milliseconds: int) -> str | None:
        """None: SQLite has no server-side statement timeout, and `busy_timeout` is not one.

        `busy_timeout` waits for a LOCK to be released; it does nothing about a query that is simply
        slow. Returning it here would be answering a different question with a value that looks
        right, which is worse than answering nothing.
        """
        return None

    def register_type(self, python_type: object, sql_type: str) -> None:
        """Adds (or rewrites) the SQL spelling of a Python type in THIS dialect.

        See `SnakeDialect.register_type`. It goes per dialect because the same Python type is
        written differently on each engine: an `Inet` is `INET` on Postgres and `TEXT` here.
        """
        self._types[python_type] = sql_type

    def placeholder(self, index: int) -> str:
        """SQLite uses a positional '?' (like psycopg2's `%s`): params in TEXTUAL ORDER for both."""
        return "?"

    def trigger_statements(self, name: str, body: str) -> tuple[list[str], str]:
        """`BEGIN ... END` around the body. Without them SQLite answers `near "UPDATE": syntax error`.

        Measured: it is not optional even for a single statement, which is the difference from MySQL
        and the reason this is three implementations and not two.

        A body that ALREADY carries them is left alone, the same rule PostgreSQL applies to a body
        that already calls a function. Wrapping blindly produced `BEGIN BEGIN SELECT 1; END END` and
        SQLite answered `near "BEGIN": syntax error` — the asymmetry was written into this very
        method, in the same session that had just fixed it one file over.
        """
        stripped = body.strip()
        if stripped.upper().startswith("BEGIN"):
            return [], stripped
        return [], f"BEGIN {body} END"

    def quote_ident(self, name: str) -> str:
        """Quotes with double quotes and doubles the inner ones (SQLite accepts the standard)."""
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    def json_get_sql(
        self, source: str, key_path: tuple[str, ...], as_type: type
    ) -> str:
        """`json_extract` with a `$.a.b` path. The CAST is kept even though SQLite types the result.

        Keeping it is not belt and braces: SQLite's `json_extract` gives back whatever the document
        held, so a `"5"` stored as text comes back as text and the comparison would be lexicographic
        — the very failure the declared type exists to stop, and the one SQLite is most prone to.
        """
        path = "$." + ".".join(key_path)
        access = f"json_extract({source}, '{path}')"
        cast = _SQLITE_CAST.get(as_type)
        return access if cast is None else f"CAST({access} AS {cast})"

    def date_shift_sql(
        self, source: str, amount_placeholder: str, unit: str, keeps_time: bool
    ) -> str:
        """`date(col, ? || ' days')` — the modifier is TEXT, built in SQL and never in Python.

        `keeps_time` is what picks the function, and it is the only dialect that needs it: SQLite has
        no date type to inspect, and `date()` on a timestamp would silently drop the clock. The
        compiled type stamped on the expression is what answers it.

        The plural is not cosmetic: SQLite's modifiers are `days`, `months`, `years`.
        """
        function = "datetime" if keeps_time else "date"
        return f"{function}({source}, {amount_placeholder} || ' {unit}s')"

    def string_agg_sql(
        self, value: str, separator: str, order_by: str, params: list[object]
    ) -> str:
        """`group_concat(col, ? ORDER BY ...)`: a different NAME, the same shape as Postgres.

        The `ORDER BY` inside the call only arrived in SQLite 3.44, which is why it was measured
        rather than assumed.
        """
        params.append(separator)
        placeholder = self.placeholder(len(params))
        inside = f"{value}, {placeholder}"
        return (
            f"group_concat({inside} ORDER BY {order_by})"
            if order_by
            else f"group_concat({inside})"
        )

    def integer_division_op(self) -> str:
        """`/` — measured: `SELECT 45/50` is `0` here too. SQLite agrees with PostgreSQL on this."""
        return "/"

    def cast_sql(self, source: str, as_type: type) -> str:
        """`CAST(x AS REAL)` — and REAL is the point, not a detail.

        MEASURED: `CAST(45 AS NUMERIC) / 50` answers `0` here and `0.9` on PostgreSQL. SQLite's
        NUMERIC affinity converts back to an integer when the value is integral, so the tempting
        single spelling for the three engines would lose the decimals on this one, in silence.
        """
        return f"CAST({source} AS {_SQLITE_CAST[as_type]})"

    def map_type(
        self,
        python_type: object,
        autoincrement: bool = False,
        params: SnakeTypeParams | None = None,
    ) -> str:
        """Translates the Python type into one of SQLite's five storage classes.

        With `autoincrement` it returns `INTEGER`: SQLite's autoincrement is `INTEGER PRIMARY KEY`
        (an alias of ROWID). The `params` are accepted but IGNORED: SQLite has a single affinity per
        class, so a width, a length or a precision have nowhere to be written. They are accepted so
        that the same model works on both engines; that they change nothing here is said by the
        dialect's fidelity warning, not by silence.
        """
        if autoincrement:
            return "INTEGER"
        origin = get_origin(python_type)
        if origin is not None:
            # SQLite has no arrays: the list falls back to TEXT and travels as JSON (`adapt_param`
            # serialises it, `_to_list` rebuilds it, so the attribute is still a list). It used to
            # be REJECTED so as not to lose the type in silence, and that was right while there was
            # no way to say so; with the degradation declared in `capabilities` there is one, and
            # rejecting only achieved that a list column existed on Postgres alone.
            if origin is list:
                return "TEXT"
            if origin is dict:
                return "TEXT"
        if isinstance(python_type, type) and issubclass(python_type, Enum):
            # An enum is stored as its BASE type (str or int) with its CHECK alongside, as on Postgres.
            base = str if issubclass(python_type, str) else int
            return _SQLITE_TYPES[base]
        try:
            return self._types[python_type]
        except (KeyError, TypeError):
            raise SnakeDialectError(
                f"SQLiteDialect does not know how to translate {python_type!r} into a SQLite type"
            ) from None

    def limit_offset(
        self, limit: int | None, offset: int | None, params: list[object]
    ) -> str:
        """A parametrised `LIMIT ? OFFSET ?`. With `offset` and no `limit` it uses `LIMIT -1`: SQLite does not accept a bare OFFSET."""
        parts: list[str] = []
        if limit is not None:
            params.append(limit)
            parts.append(f"LIMIT {self.placeholder(len(params))}")
        elif offset is not None:
            parts.append("LIMIT -1")
        if offset is not None:
            params.append(offset)
            parts.append(f"OFFSET {self.placeholder(len(params))}")
        return " ".join(parts)

    def on_conflict_clause(
        self, conflict_columns: Sequence[str], update_columns: Sequence[str]
    ) -> str:
        """`ON CONFLICT (<cols>) DO NOTHING` / `DO UPDATE SET c = excluded.c`. Like Postgres, but with `excluded` in lower case."""
        conflict = ", ".join(self.quote_ident(column) for column in conflict_columns)
        if not update_columns:
            return f"ON CONFLICT ({conflict}) DO NOTHING"
        assignments = ", ".join(
            f"{self.quote_ident(column)} = excluded.{self.quote_ident(column)}"
            for column in update_columns
        )
        return f"ON CONFLICT ({conflict}) DO UPDATE SET {assignments}"

    def literal(self, value: object) -> str:
        """Formats a value as a SQLite SQL literal (DDL, no params).
        A bool goes as 0/1: SQLite has no boolean type, it stores integers.
        """
        if isinstance(value, Enum):
            value = value.value
        if value is None:
            return "NULL"
        if isinstance(value, bool):  # before int: bool is a subclass of int
            return "1" if value else "0"
        if isinstance(value, (int, float, Decimal)):
            return numeric_literal(value, "SQLiteDialect")
        if isinstance(value, str):
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        raise SnakeDialectError(
            f"SQLiteDialect does not know how to format {value!r} as a SQL literal"
        )

    def function_name(self, func: SnakeFunc) -> str:
        """Translates the agnostic name of a scalar function into SQLite's own."""
        if func in _SQLITE_FUNCTIONS:
            return _SQLITE_FUNCTIONS[func]
        reason = _SQLITE_CANNOT.get(func)
        if reason is None:
            # Not a catalogue member at all. A real one cannot reach here: the import
            # guard above refuses to load a dialect that skipped any.
            raise SnakeDialectError(
                f"SQLiteDialect does not know how to translate the function {func!r}"
            )
        raise SnakeDialectError(
            f"SQLiteDialect cannot translate {func.name}: {reason} "
            "Reach for it through `raw()` with the engine's own spelling."
        )

    def index_method(self, method: SnakeIndexMethod) -> str:
        """SQLite has ONE kind of index: there is no `USING`.
        It is rejected instead of ignored: accepting `method=GIN` and emitting a plain index would lie in silence.
        """
        raise SnakeDialectError(
            f"SQLite has only one kind of index, so it does not accept method={method.name}. "
            f"Drop the `method=` for this engine."
        )

    def server_default_sql(self, value: SnakeServerDefault) -> str:
        """Translates the server-side default into its SQLite expression."""
        try:
            return _SQLITE_SERVER_DEFAULTS[value]
        except KeyError:
            raise SnakeDialectError(
                f"SQLiteDialect does not know how to translate the server_default {value!r} to SQL"
            ) from None

    def __repr__(self) -> str:
        """The dialect's name, useful in the capability error messages."""
        return "SQLiteDialect()"


_SQLITE_CAST = {int: "INTEGER", float: "REAL", bool: "INTEGER"}
"""What a declared type becomes in a SQLite cast. `str` is absent: the value is already text,
and SQLite has no boolean, so a bool is the INTEGER it stores."""
