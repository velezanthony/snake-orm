"""PostgreSQL introspector: it reads `information_schema`/`pg_catalog` and returns the graph."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from snakeorm.core.exceptions import SnakeMigrationError, SnakeModelDefinitionError
from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.drivers import SnakeDriver
from snakeorm.introspection.unsupported import (
    SnakeUnsupportedKind,
    warnings_from_rows,
)
from snakeorm.times import SnakeUtc
from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeDateTimeParams,
    SnakeDecimalParams,
    SnakeForeignKeyInfo,
    SnakeIndexInfo,
    SnakeIntParams,
    SnakeIntSize,
    SnakeJsonParams,
    SnakeJsonStorage,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeStrParams,
    SnakeTableInfo,
    SnakeTypeParams,
)

# The INVERSE Postgres → Python mapping. It is not the exact inverse of `_POSTGRES_TYPES`: several
# SQL types collapse onto the same Python one (`text`/`varchar`/`char` → `str`). Introspection is
# not bijective.
_PYTHON_TYPES: dict[str, type] = {
    "integer": int,
    "bigint": int,
    "smallint": int,
    "text": str,
    "character varying": str,
    "character": str,
    "boolean": bool,
    "double precision": float,
    "real": float,
    "numeric": Decimal,
    "bytea": bytes,
    "date": date,
    # Postgres's TWO date types are different and the mirror has to tell them apart: the first
    # stores an INSTANT (and in Python that is `SnakeUtc`), the second a WALL-CLOCK TIME.
    # Collapsing them into `datetime` meant scaffolding a TIMESTAMPTZ produced a model that says
    # TIMESTAMP — without blowing up, and without anybody noticing until the next `drift`.
    "timestamp with time zone": SnakeUtc,
    "timestamp without time zone": datetime,
    "time without time zone": time,
    "interval": timedelta,
    "uuid": UUID,
    "jsonb": dict,
    "json": dict,
}

# The width of the integer read → its `int_size`, so scaffolding re-emits the SAME type. Without
# this a legacy `INTEGER` would come back with the default `BIGINT` and the generated file would
# widen it in silence.
_INT_SIZES: dict[str, SnakeIntSize] = {
    "smallint": SnakeIntSize.SMALLINT,
    "integer": SnakeIntSize.INTEGER,
    "bigint": SnakeIntSize.BIGINT,
}

# Postgres's two date types -> whether the column carries a time zone. The mirror has to tell them
# apart: they are DIFFERENT types in the database, and each has its own declarator.
_TIMESTAMP_TZ: dict[str, bool] = {
    "timestamp with time zone": True,
    "timestamp without time zone": False,
}

# The backing of the JSON read from the database → its knob, so scaffolding does not drift (a legacy
# `json` is not re-emitted as `jsonb`, which would normalise it).
_JSON_STORAGES: dict[str, SnakeJsonStorage] = {
    "jsonb": SnakeJsonStorage.JSONB,
    "json": SnakeJsonStorage.JSON,
}


def _type_params(
    data_type: str, max_length: int | None, precision: int | None, scale: int | None
) -> SnakeTypeParams | None:
    """The parameters of the family the type read from the database really belongs to.

    All FIVE knobs used to be fired at every column, so an `integer` came back carrying a
    `json_storage=JSONB` and a `max_length=None` that meant nothing. With one object per family you
    have to CHOOSE one, and choosing forces you to look at the type — which is the right thing.

    `None` for whatever has no parameters, including a `numeric` WITHOUT precision: Postgres allows
    the unconstrained NUMERIC and the mirror must be able to reproduce it as it is.

    The parameters validate their own range, and here nobody writes the values: the database brings
    them. A `NUMERIC` with a negative scale —a Postgres 15 extension, which the ORM does not model—
    would trip that guard with a message telling the user about what they "declared", when they
    declared nothing. It is translated into an INTROSPECTION error, which is what really happened.
    """
    if data_type == "numeric":
        if precision is None:
            return None
        try:
            return SnakeDecimalParams(precision, scale)
        except SnakeModelDefinitionError as error:
            raise SnakeMigrationError(
                f"The database has a NUMERIC({precision},{scale}) this ORM cannot declare: "
                f"{error} If it comes from a Postgres 15 extension (negative scales, or scales "
                f"larger than the precision), the mirror cannot reproduce it: exclude that column "
                f"or redeclare it in the database."
            ) from error
    if data_type in _TIMESTAMP_TZ:
        # The time zone HAS to travel in the parameters, not be deduced from the Python type later:
        # the generator picks the declarator by reading `with_timezone`, and without these
        # parameters it read the default (`False`) and emitted `snake_datetime()` over a
        # `SnakeColumn[SnakeUtc]` — a contradiction its own guard rejects. Scaffolding a
        # TIMESTAMPTZ produced a file that does not import.
        return SnakeDateTimeParams(tz=_TIMESTAMP_TZ[data_type])
    if data_type in _INT_SIZES:
        return SnakeIntParams(size=_INT_SIZES[data_type])
    if data_type in _JSON_STORAGES:
        return SnakeJsonParams(storage=_JSON_STORAGES[data_type])
    if max_length is not None:
        return SnakeStrParams(max_length=max_length)
    return None


_UNSUPPORTED_QUERY = f"""
SELECT '{SnakeUnsupportedKind.TRIGGER.value}',
       t.tgname::text, c.relname::text, NULL
  FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE NOT t.tgisinternal AND n.nspname = %s
UNION ALL
SELECT '{SnakeUnsupportedKind.EXPRESSION_INDEX.value}',
       i.relname::text, NULL, NULL
  FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
  JOIN pg_class c ON c.oid = x.indrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = %s AND x.indexprs IS NOT NULL
UNION ALL
SELECT '{SnakeUnsupportedKind.UNREPRESENTABLE_COLUMN.value}',
       c.relname::text, a.attname::text, format_type(a.atttypid, a.atttypmod)
  FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = %s AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
   AND format_type(a.atttypid, NULL) NOT IN (
       'integer','bigint','smallint','text','character varying','character','boolean',
       'double precision','real','numeric','bytea','date','timestamp with time zone',
       'timestamp without time zone','time without time zone','interval','uuid','jsonb','json')
UNION ALL
SELECT '{SnakeUnsupportedKind.CHECK.value}',
       k.conname::text, c.relname::text, pg_get_constraintdef(k.oid)
  FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE k.contype = 'c' AND n.nspname = %s
ORDER BY 1, 2, 3
"""
"""What the graph cannot represent, TAGGED but not worded.

The three engines used to compose the sentence inside their own SQL and drifted apart doing it — one
of them into Spanish. Here the query only says WHAT it found and hands over the pieces;
`introspection.unsupported` writes the sentence for all three. The kinds are interpolated from that
same enum rather than retyped, so a rename cannot leave this query behind quietly.

The literals interpolated here are this module's own constants, never a value from the database: the
parameters are still the three `%s`, which is where anything from outside travels.
"""


class PostgresIntrospector:
    """Reads Postgres's real schema. Implements the `SnakeIntrospector` Protocol."""

    def __init__(self, driver: SnakeDriver) -> None:
        self._driver = driver

    def tables(self, schema: str = DEFAULT_SCHEMA) -> list[SnakeTableInfo]:
        """Reads the schema's tables with everything the graph knows how to represent."""
        names = [
            str(row[0])
            for row in self._driver.fetch_all(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
                "AND table_name <> 'snake_migrations' ORDER BY table_name",
                (schema,),
            )
        ]
        return [self._table(schema, name) for name in names]

    def _table(self, schema: str, name: str) -> SnakeTableInfo:
        """Builds the `SnakeTableInfo` of one specific table."""
        primary_key_columns = self._primary_key_columns(schema, name)
        unique_columns = self._unique_columns(schema, name)
        comments = self._column_comments(schema, name)
        columns = [
            self._column(row, unique_columns, comments)
            for row in self._driver.fetch_all(
                "SELECT column_name, data_type, is_nullable, column_default, "
                "character_maximum_length, numeric_precision, numeric_scale "
                "FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                (schema, name),
            )
        ]
        by_name = {column.name: column for column in columns}
        return SnakeTableInfo(
            name=name,
            columns=tuple(columns),
            primary_key=SnakePrimaryKeyInfo(
                columns=tuple(
                    by_name[column]
                    for column in primary_key_columns
                    if column in by_name
                )
            ),
            relationships=self._relationships(schema, name),
            schema=schema,
            db_comment=self._table_comment(schema, name),
            indexes=self._indexes(schema, name),
        )

    def _column(
        self,
        row: tuple[object, ...],
        unique_columns: set[str],
        comments: dict[str, str],
    ) -> SnakeColumnInfo:
        """Translates a row of `information_schema.columns` into column metadata."""
        name, data_type, nullable, default = (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            row[3],
        )
        # `nextval(...)` is how Postgres represents a SERIAL: it is recognised by the default, not
        # by the type, because the type is still `integer`.
        autoincrement = isinstance(default, str) and default.startswith("nextval(")
        # `character_maximum_length` only comes on VARCHAR(n)/CHAR(n); on TEXT it is NULL. That way
        # a faithful scaffolding re-emits the original VARCHAR(n) instead of widening it to TEXT.
        max_length = row[4] if isinstance(row[4], int) else None
        # precision/scale ONLY for NUMERIC: an `integer` also brings a numeric_precision (32), but
        # there it means nothing. Without this, `NUMERIC(10,2)` came back as a bare `NUMERIC`.
        is_numeric = data_type == "numeric"
        precision = row[5] if is_numeric and isinstance(row[5], int) else None
        scale = row[6] if is_numeric and isinstance(row[6], int) else None
        # The DEFAULT is a SQL expression (`now()`, `'x'::text`), not a literal: it is preserved as
        # `server_default_sql`. The SERIAL's nextval is already captured by `autoincrement`, it is
        # not duplicated.
        server_default_sql = (
            default if isinstance(default, str) and not autoincrement else None
        )
        return SnakeColumnInfo(
            name=name,
            python_type=_PYTHON_TYPES.get(data_type, str),
            nullable=nullable == "YES",
            unique=name in unique_columns,
            attr_name=name,
            autoincrement=autoincrement,
            db_comment=comments.get(name),
            server_default_sql=server_default_sql,
            type_params=_type_params(data_type, max_length, precision, scale),
        )

    def _primary_key_columns(self, schema: str, name: str) -> list[str]:
        """The PK's columns, IN ORDER (it matters for a composite PK)."""
        rows = self._driver.fetch_all(
            "SELECT a.attname FROM pg_index x "
            "JOIN pg_class c ON c.oid = x.indrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(x.indkey) "
            "WHERE x.indisprimary AND n.nspname = %s AND c.relname = %s "
            "ORDER BY array_position(x.indkey, a.attnum)",
            (schema, name),
        )
        return [str(row[0]) for row in rows]

    def _unique_columns(self, schema: str, name: str) -> set[str]:
        """Columns with a UNIQUE constraint over a SINGLE column."""
        rows = self._driver.fetch_all(
            "SELECT a.attname FROM pg_constraint k "
            "JOIN pg_class c ON c.oid = k.conrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(k.conkey) "
            "WHERE k.contype = 'u' AND array_length(k.conkey, 1) = 1 "
            "AND n.nspname = %s AND c.relname = %s",
            (schema, name),
        )
        return {str(row[0]) for row in rows}

    def _indexes(self, schema: str, name: str) -> tuple[SnakeIndexInfo, ...]:
        """NON-unique indexes not derived from a constraint (those already come out as uniqueness)."""
        rows = self._driver.fetch_all(
            "SELECT i.relname, array_agg(a.attname ORDER BY a.attnum) "
            "FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid "
            "JOIN pg_class c ON c.oid = x.indrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(x.indkey) "
            "WHERE n.nspname = %s AND c.relname = %s "
            "AND NOT x.indisprimary AND NOT x.indisunique AND x.indexprs IS NULL "
            "GROUP BY i.relname ORDER BY i.relname",
            (schema, name),
        )
        return tuple(
            SnakeIndexInfo(
                columns=tuple(
                    str(column)
                    for column in (row[1] if isinstance(row[1], list) else [])
                ),
                name=str(row[0]),
            )
            for row in rows
        )

    def _relationships(
        self, schema: str, name: str
    ) -> tuple[SnakeRelationshipInfo, ...]:
        """The table's foreign keys, with their pairs (local column → remote column)."""
        rows = self._driver.fetch_all(
            # `unnest(conkey, confkey) WITH ORDINALITY` walks the two key arrays TOGETHER, one
            # position at a time. Joining `pg_attribute` twice with `= ANY(...)` instead — which is
            # what this did — is a CARTESIAN PRODUCT: a two-column key matched 2 local rows by 2
            # remote ones and aggregated FOUR, each name twice. One column is 1x1, so it looked
            # right for every single-column key in the suite.
            #
            # The ordering was the second half of the same bug: `ORDER BY attnum` is the order the
            # columns were DECLARED in the table, not their position in the key, so a composite key
            # whose columns are not in declaration order paired the wrong ones together.
            "SELECT k.conname, tc.relname, "
            "  array_agg(la.attname ORDER BY u.ord), "
            "  array_agg(ra.attname ORDER BY u.ord) "
            "FROM pg_constraint k "
            "JOIN pg_class c ON c.oid = k.conrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_class tc ON tc.oid = k.confrelid "
            "JOIN LATERAL unnest(k.conkey, k.confkey) WITH ORDINALITY AS u(lnum, rnum, ord) "
            "  ON TRUE "
            "JOIN pg_attribute la ON la.attrelid = c.oid AND la.attnum = u.lnum "
            "JOIN pg_attribute ra ON ra.attrelid = tc.oid AND ra.attnum = u.rnum "
            "WHERE k.contype = 'f' AND n.nspname = %s AND c.relname = %s "
            "GROUP BY k.conname, tc.relname ORDER BY k.conname",
            (schema, name),
        )
        return tuple(self._relationship(row) for row in rows)

    def _relationship(self, row: tuple[object, ...]) -> SnakeRelationshipInfo:
        """Translates an FK row into relationship metadata.

        The `array_agg`s arrive as `object` from the driver (which promises tuples of `object`, not
        of lists), so they are narrowed with `isinstance` instead of being annotated: `object`,
        never `Any`, which is the discipline of the rest of the project.
        """
        target = str(row[1])
        local = row[2] if isinstance(row[2], list) else []
        remote = row[3] if isinstance(row[3], list) else []
        pairs = tuple(
            (str(source_column), str(target_column))
            for source_column, target_column in zip(local, remote, strict=False)
        )
        return SnakeRelationshipInfo(
            name=target,
            target=target,
            kind=SnakeRelationshipKind.TO_ONE,
            foreign_key=SnakeForeignKeyInfo(target=target, pairs=pairs),
        )

    def _table_comment(self, schema: str, name: str) -> str | None:
        """The table's comment, if it has one."""
        rows = self._driver.fetch_all(
            "SELECT obj_description(c.oid) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s",
            (schema, name),
        )
        return str(rows[0][0]) if rows and rows[0][0] is not None else None

    def _column_comments(self, schema: str, name: str) -> dict[str, str]:
        """Comments per column."""
        rows = self._driver.fetch_all(
            "SELECT a.attname, col_description(c.oid, a.attnum) FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped",
            (schema, name),
        )
        return {str(row[0]): str(row[1]) for row in rows if row[1] is not None}

    def unsupported(self, schema: str = DEFAULT_SCHEMA) -> list[str]:
        """Objects the ORM cannot represent, described so it can WARN (never dropped in silence)."""
        rows = self._driver.fetch_all(
            _UNSUPPORTED_QUERY, (schema, schema, schema, schema)
        )
        return warnings_from_rows(rows)
