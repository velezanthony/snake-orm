"""PostgreSQL dialect."""

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
    DerivedFlags,
    Full,
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
    SnakeJsonParams,
    SnakeJsonStorage,
    SnakeServerDefault,
    SnakeFloatParams,
    SnakeStrParams,
    SnakeTimeParams,
    SnakeTypeParams,
)

# Scalar function (agnostic) -> its name on Postgres. The table centralises the per-engine mapping.
_POSTGRES_FUNCTIONS: dict[SnakeFunc, str] = {
    SnakeFunc.LOWER: "LOWER",
    SnakeFunc.UPPER: "UPPER",
    SnakeFunc.TRIM: "TRIM",
    SnakeFunc.LENGTH: "LENGTH",
    SnakeFunc.CONCAT: "CONCAT",
    SnakeFunc.DATE_TRUNC: "DATE_TRUNC",
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

# Index method (agnostic) -> Postgres's jargon. `BTREE` does not appear: it is the default, implicit without `USING`.
_POSTGRES_INDEX_METHODS: dict[SnakeIndexMethod, str] = {
    SnakeIndexMethod.HASH: "HASH",
    SnakeIndexMethod.GIN: "GIN",
    SnakeIndexMethod.GIST: "GIST",
    SnakeIndexMethod.BRIN: "BRIN",
}

# Server-side default (agnostic) -> its SQL expression on Postgres. `NOW` uses the standard
# `CURRENT_TIMESTAMP`, not `now()`; `UUID_V4` uses `gen_random_uuid()`.

_POSTGRES_CANNOT: dict[SnakeFunc, str] = {}
"""What the engine genuinely cannot do, and why.

Declared rather than left out: a function missing from the table above reads exactly like one
nobody got round to, and silence meaning two different things is how `ABS` and `ROUND` sat absent
from SQLite while the other two had both.
"""

_missing = set(SnakeFunc) - set(_POSTGRES_FUNCTIONS) - set(_POSTGRES_CANNOT)
if (
    _missing
):  # pragma: no cover - the guard exists so this can never be reached in a good build
    raise SnakeDialectError(
        "PostgresDialect does not answer for every scalar function: "
        f"{sorted(f.name for f in _missing)}. Add it to _POSTGRES_FUNCTIONS, or to _POSTGRES_CANNOT "
        "with the reason. Like the `Cap` catalogue, forgetting one fails at import."
    )

_POSTGRES_SERVER_DEFAULTS: dict[SnakeServerDefault, str] = {
    SnakeServerDefault.NOW: "CURRENT_TIMESTAMP",
    SnakeServerDefault.UUID_V4: "gen_random_uuid()",
    SnakeServerDefault.TRUE: "TRUE",
    SnakeServerDefault.FALSE: "FALSE",
    SnakeServerDefault.ZERO: "0",
}

# An integer's width -> its type on Postgres, which really does tell them apart (2/4/8 bytes), unlike SQLite.
_POSTGRES_INT_SIZES: dict[SnakeIntSize, str] = {
    SnakeIntSize.SMALLINT: "SMALLINT",
    SnakeIntSize.INTEGER: "INTEGER",
    SnakeIntSize.BIGINT: "BIGINT",
}

# The SERIAL family for the autoincrement: the PK's width rules. Emitting `SERIAL` (int4) for a PK
# declared wide would leave it short in silence.
_POSTGRES_SERIALS: dict[SnakeIntSize, str] = {
    SnakeIntSize.SMALLINT: "SMALLSERIAL",
    SnakeIntSize.INTEGER: "SERIAL",
    SnakeIntSize.BIGINT: "BIGSERIAL",
}

# Python type -> Postgres SQL type. `int` and `dict` are NOT here: their type depends on a knob
# (`int_size`, `json_storage`) that `map_type` resolves.
_POSTGRES_TYPES: dict[object, str] = {
    str: "TEXT",
    bool: "BOOLEAN",
    float: "DOUBLE PRECISION",
    Decimal: "NUMERIC",
    bytes: "BYTEA",
    date: "DATE",
    # The TWO date types, which are different types in the database and not a knob: `SnakeUtc` stores
    # an INSTANT (TIMESTAMPTZ: the moment, without the offset it was written with) and a plain
    # `datetime` a WALL-CLOCK TIME (TIMESTAMP), which identifies no instant until somebody says what
    # zone it is in. The declarator picks it —`snake_datetimetz()` / `snake_datetime()`— and a guard
    # in the compiler demands that it match the annotation.
    SnakeUtc: "TIMESTAMPTZ",
    datetime: "TIMESTAMP",
    time: "TIME",
    timedelta: "INTERVAL",
    UUID: "UUID",
}


def _element_type(annotation: object) -> object:
    """The element type of a `list[...]`; it fails clearly if the list does not declare it."""
    args = get_args(annotation)
    if not args:
        raise SnakeDialectError(
            f"{annotation!r} does not declare its element type: there is no untyped array in "
            f"SQL. Annotate it as `list[int]`, `list[str]`, etc."
        )
    return args[0]


class PostgresDialect(DerivedFlags):
    """How the SQL is written for PostgreSQL (psycopg2 driver).

    Placeholder '%s'; it depends on the driver (asyncpg would use '$1'), today only psycopg2.
    """

    # It answers `Full()` to the WHOLE catalogue, and that is a fact, not a template: it is the only
    # engine with no caveats, and that is why it is the yardstick the other two are measured against.
    # `caveats()` being empty here is what makes the session emit no warning at all about Postgres.
    capabilities = SnakeCapabilities({cap: Full() for cap in Cap})

    syntax = SnakeSyntax(
        triggers_are_table_scoped=True,  # `DROP TRIGGER x ON table`
        indexes_are_table_scoped=False,  # `DROP INDEX x`, without `ON table`
        empty_insert_style=EmptyInsertStyle.DEFAULT_VALUES,
        alter_column_style=AlterColumnStyle.POSTGRES_TYPE_USING,
        comment_style=CommentStyle.COMMENT_ON,  # `COMMENT ON TABLE t IS 'x'`, a statement of its own
        has_ilike=True,
        has_nulls_ordering=True,
        # `ROUND(double precision, int)` does not exist here; `ROUND(numeric, int)` does.
        round_casts_first_argument_to="numeric",
    )

    # Ceilings of the declared parameters. They live here, and not in the metadata, because they
    # belong to the ENGINE: the model has to be able to say NUMERIC(500,2) without knowing which
    # database it will end up on.
    limits = SnakeLimits(
        bind_params=65535,  # unsigned int16 in the protocol
        numeric_precision=1000,
        numeric_scale=1000,  # the standard already demands scale <= precision
        fractional_seconds=6,  # microseconds: the resolution of Python's datetime
    )

    def placeholder(self, index: int) -> str:
        """psycopg2 uses a positional '%s'; the index is not needed on this engine."""
        return "%s"

    def trigger_statements(self, name: str, body: str) -> tuple[list[str], str]:
        """The body goes in a function and the trigger calls it: PostgreSQL takes no statements here.

        A body that ALREADY calls a function is left alone — wrapping it would make a function that
        calls a function. `RETURN NEW` is appended because a trigger function must return something,
        and for an `AFTER` trigger the value is ignored but its absence is an error.
        """
        if body.strip().upper().startswith(("EXECUTE FUNCTION", "EXECUTE PROCEDURE")):
            return [], body
        function = self.quote_ident(f"{name}_fn")
        return (
            [
                f"CREATE OR REPLACE FUNCTION {function}() RETURNS trigger AS $$ "
                f"BEGIN {body} RETURN NEW; END; $$ LANGUAGE plpgsql"
            ],
            f"EXECUTE FUNCTION {function}()",
        )

    def quote_ident(self, name: str) -> str:
        """Quotes with double quotes and doubles the inner quotes."""
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    def json_get_sql(
        self, source: str, key_path: tuple[str, ...], as_type: type
    ) -> str:
        """`->>` for one key, `#>>` with a `{a,b}` path for several, cast to the declared type.

        `str` gets NO cast: `->>` already returns text, and a `::text` on every statement would be
        noise saying nothing. The others do, because without it the comparison is a TEXT comparison
        and `'9' > '100'` is true.
        """
        if len(key_path) == 1:
            access = f"({source} ->> '{key_path[0]}')"
        else:
            access = f"({source} #>> '{{{','.join(key_path)}}}')"
        cast = _PG_CAST.get(as_type)
        return access if cast is None else f"({access})::{cast}"

    def date_shift_sql(
        self, source: str, amount_placeholder: str, unit: str, keeps_time: bool
    ) -> str:
        """`(col + (%s * INTERVAL '1 day'))`, and the multiplication is what parameterises it.

        `INTERVAL '30 days'` would mean interpolating the amount into the statement. Multiplying a
        ONE-unit interval by a placeholder was measured to answer the same date and keeps the value
        in `params`, where every value in this ORM belongs. `keeps_time` is unused: Postgres has real
        date and timestamp types and the result follows the operand.
        """
        return f"({source} + ({amount_placeholder} * INTERVAL '1 {unit}'))"

    def string_agg_sql(
        self, value: str, separator: str, order_by: str, params: list[object]
    ) -> str:
        """`STRING_AGG(col, %s ORDER BY ...)`: the separator is an argument, so it parameterises."""
        params.append(separator)
        placeholder = self.placeholder(len(params))
        inside = f"{value}, {placeholder}"
        return (
            f"STRING_AGG({inside} ORDER BY {order_by})"
            if order_by
            else f"STRING_AGG({inside})"
        )

    def integer_division_op(self) -> str:
        """`/` — measured: `SELECT 45/50` is `0` here, of type `integer`. Nothing to translate."""
        return "/"

    def cast_sql(self, source: str, as_type: type) -> str:
        """`CAST(x AS double precision)`, reading the SAME table `json_get_sql` reads.

        Two tables of one thing drift, and the one that drifts is the one with fewer readers.
        """
        return f"CAST({source} AS {_PG_CAST[as_type]})"

    def __init__(self) -> None:
        # A PER-INSTANCE copy of the type table: `register_type` writes here, not into the module's
        # dict. If it were global, importing a library that registers a type would sneak it into
        # every dialect in the process, including those of a database that does not support it.
        self._types: dict[object, str] = dict(_POSTGRES_TYPES)

    def drop_all_sql(self, tables: Sequence[str]) -> tuple[str, ...]:
        """`DROP TABLE IF EXISTS ... CASCADE`, one per table: Postgres resolves the order itself.

        `CASCADE` drops whatever depends on the table —the foreign keys pointing at it, the views
        built on it— so no bracketing switch is needed and the order does not matter.
        """
        return tuple(
            f"DROP TABLE IF EXISTS {self.quote_ident(table)} CASCADE"
            for table in tables
        )

    def explain_sql(self, sql: str) -> str:
        """`EXPLAIN <statement>`: one text column per line of the plan."""
        return f"EXPLAIN {sql}"

    def statement_timeout_sql(self, milliseconds: int) -> str | None:
        """`SET statement_timeout`, already in milliseconds: no conversion needed."""
        return f"SET statement_timeout = {milliseconds}"

    def register_type(self, python_type: object, sql_type: str) -> None:
        """Adds (or rewrites) the SQL spelling of a Python type in THIS dialect.

            dialect.register_type(Inet, "INET")
            address: SnakeColumn[Inet] = snake_column()

        It is the extension point the thesis was missing: the type system was the single source of
        truth, but its VOCABULARY was closed and putting in an `INET`, a `CITEXT` or a domain type
        meant editing the dialect. It goes per dialect because the same Python type is written
        differently on each engine, which is exactly what this axis exists for.

        Rewriting a native type is allowed (e.g. `str` → `CITEXT` across the whole database): it is
        an explicit escape hatch, and forbidding it would force forking the entire dialect over one
        line.
        """
        self._types[python_type] = sql_type

    def _guard_numeric(self, params: SnakeDecimalParams) -> None:
        """Checks that the declared NUMERIC fits within what Postgres accepts.

        Whatever is structurally impossible already died at declaration time; all that is left here
        is the engine's ceiling, which is different on each one: `NUMERIC(500,2)` is valid and on
        MySQL it would be impossible.
        """
        assert self.max_numeric_precision is not None
        if params.precision > self.max_numeric_precision:
            raise SnakeDialectError(
                f"Postgres does not accept more than {self.max_numeric_precision} digits in a "
                f"NUMERIC, and {params.precision} were requested. If you need more, the column is "
                f"not a NUMERIC: store the number as text and operate outside the database."
            )

    def map_type(
        self,
        python_type: object,
        autoincrement: bool = False,
        params: SnakeTypeParams | None = None,
    ) -> str:
        """Translates the Python type into its COMPLETE Postgres type, parameters included.

        It accepts `object`, not `type`: `list[int]` is a generic alias, not a class, and is
        resolved by origin+argument; a bare `list` is rejected (an array with no element type does
        not exist in SQL).

        `params` are those of the type's FAMILY and arrive as ONE object, not as five loose knobs.
        `precision` being one more of them is not cosmetic: it used to be glued onto the type from
        outside here, with an f-string in `migration/ddl.py`, and that is why it was the only
        parameter nobody validated.
        """
        # The TYPE rules; the `params` only FINE-TUNE. The other way round (dispatching by the
        # params family) an `int` column with no parameters would not find its branch, because `int`
        # and `dict` are not in the table: their SQL type always depended on a parameter and their
        # default lives here.
        if python_type is int:
            size = (
                params.size
                if isinstance(params, SnakeIntParams)
                else SnakeIntSize.BIGINT
            )
            # The integer PK rules its width: BIGINT->BIGSERIAL, INTEGER->SERIAL, SMALLINT->SMALLSERIAL.
            return (
                _POSTGRES_SERIALS[size] if autoincrement else _POSTGRES_INT_SIZES[size]
            )
        if autoincrement:
            return _POSTGRES_SERIALS[SnakeIntSize.BIGINT]
        # `base_type`: a `dict[str, object]` IS a dict column. Comparing the annotation
        # itself let a parameterised one fall through to the default type, so the column
        # came out TEXT and the JSON storage the user asked for was silently dropped.
        if base_type(python_type) is dict:
            # JSONB (indexable) or JSON (exact text). The member IS the literal type.
            storage = params.storage if isinstance(params, SnakeJsonParams) else None
            return (
                storage.value if storage is not None else SnakeJsonStorage.JSONB.value
            )
        if (
            python_type is str
            and isinstance(params, SnakeStrParams)
            and params.max_length
        ):
            # VARCHAR(n) = TEXT + a limit. It is not faster; it STATES a domain rule.
            # With `fixed`, CHAR(n): a FIXED length, which pads with spaces and compares ignoring them.
            return (
                f"CHAR({params.max_length})"
                if params.fixed
                else f"VARCHAR({params.max_length})"
            )
        if python_type is float and isinstance(params, SnakeFloatParams):
            # 4 bytes or 8. The default (8) comes from the type table, so that `register_type` can
            # rewrite it; the 4 is an explicit storage decision.
            return "REAL" if params.size == 4 else self._types[float]
        if python_type is time and isinstance(params, SnakeTimeParams):
            # The column's TYPE is decided by the declarator, not by whatever value arrives first.
            # It is the same doctrine that split snake_datetime from snake_datetimetz.
            return "TIMETZ" if params.with_timezone else self._types[time]
        if isinstance(python_type, type) and issubclass(python_type, datetime):
            # The TYPE decides the time zone, not a knob, and each one's spelling comes from the
            # TABLE instead of being repeated here. It is not cosmetic: while the branch carried its
            # own two literals, the table said `datetime -> TIMESTAMPTZ` and was never read, so it
            # was carrying the OLD doctrine with nothing to give it away. An entry nobody runs is an
            # entry nobody fixes. On top of that, `register_type()` now works on a subclass of your
            # own.
            base = self._types.get(python_type)
            if base is None:
                base = self._types[
                    SnakeUtc if issubclass(python_type, SnakeUtc) else datetime
                ]
            digits = (
                params.precision if isinstance(params, SnakeDateTimeParams) else None
            )
            assert self.max_fractional_seconds is not None
            if digits is not None and digits > self.max_fractional_seconds:
                raise SnakeDialectError(
                    f"Postgres does not store more than {self.max_fractional_seconds} "
                    f"fractional-second digits, and {digits} were requested. With "
                    f"{self.max_fractional_seconds} you already reach microseconds, which is the "
                    f"whole resolution Python's datetime has."
                )
            return base if digits is None else f"{base}({digits})"
        if python_type is Decimal and isinstance(params, SnakeDecimalParams):
            # The precision is emitted HERE. It used to be concatenated in `migration/ddl.py`,
            # outside the dialect, and that is why it was the only parameter that never went through
            # a validation.
            self._guard_numeric(params)
            scale = f",{params.scale}" if params.scale is not None else ""
            return f"NUMERIC({params.precision}{scale})"
        origin = get_origin(python_type)
        if origin is list or python_type is list:
            return f"{self.map_type(_element_type(python_type))}[]"
        try:
            return self._types[python_type]
        except (KeyError, TypeError):
            raise SnakeDialectError(
                f"PostgresDialect does not know how to map {python_type!r} to a SQL type. If it "
                f"is a type of your own, or a Postgres one the ORM does not ship with, register "
                f"it: "
                f'dialect.register_type({getattr(python_type, "__name__", python_type)}, "INET")'
            ) from None

    def limit_offset(
        self, limit: int | None, offset: int | None, params: list[object]
    ) -> str:
        """A parametrised `LIMIT %s OFFSET %s` (Postgres accepts parameters in both)."""
        parts: list[str] = []
        if limit is not None:
            params.append(limit)
            parts.append(f"LIMIT {self.placeholder(len(params))}")
        if offset is not None:
            params.append(offset)
            parts.append(f"OFFSET {self.placeholder(len(params))}")
        return " ".join(parts)

    def on_conflict_clause(
        self, conflict_columns: Sequence[str], update_columns: Sequence[str]
    ) -> str:
        """`ON CONFLICT (<cols>) DO NOTHING`; with `update_columns`, `DO UPDATE SET c = EXCLUDED.c`.
        `EXCLUDED` is the row that was attempted, so the UPDATE rewrites with the incoming value.
        """
        conflict = ", ".join(self.quote_ident(column) for column in conflict_columns)
        if not update_columns:
            return f"ON CONFLICT ({conflict}) DO NOTHING"
        assignments = ", ".join(
            f"{self.quote_ident(column)} = EXCLUDED.{self.quote_ident(column)}"
            for column in update_columns
        )
        return f"ON CONFLICT ({conflict}) DO UPDATE SET {assignments}"

    def literal(self, value: object) -> str:
        """Formats a default value as a Postgres SQL literal (DDL DEFAULT).
        The enum is unwrapped to its value EXPLICITLY, without relying on IntEnum/StrEnum's `str()`.
        """
        if isinstance(value, Enum):
            value = value.value
        if value is None:
            return "NULL"
        if isinstance(value, bool):  # before int: bool is a subclass of int
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float, Decimal)):
            return numeric_literal(value, "PostgresDialect")
        if isinstance(value, str):
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        raise SnakeDialectError(
            f"PostgresDialect does not know how to format {value!r} as a SQL literal"
        )

    def function_name(self, func: SnakeFunc) -> str:
        """Translates the agnostic name of a scalar function into the engine's own."""
        if func in _POSTGRES_FUNCTIONS:
            return _POSTGRES_FUNCTIONS[func]
        reason = _POSTGRES_CANNOT.get(func)
        if reason is None:
            # Not a catalogue member at all. A real one cannot reach here: the import
            # guard above refuses to load a dialect that skipped any.
            raise SnakeDialectError(
                f"PostgresDialect does not know how to translate the function {func!r}"
            )
        raise SnakeDialectError(
            f"PostgresDialect cannot translate {func.name}: {reason} "
            "Reach for it through `raw()` with the engine's own spelling."
        )

    def index_method(self, method: SnakeIndexMethod) -> str:
        """Translates the index method (agnostic) into Postgres's jargon for the `USING`."""
        try:
            return _POSTGRES_INDEX_METHODS[method]
        except KeyError:
            raise SnakeDialectError(
                f"PostgresDialect does not know how to translate the index method {method!r}"
            ) from None

    def server_default_sql(self, value: SnakeServerDefault) -> str:
        """Translates the server-side default (agnostic) into its Postgres SQL expression."""
        try:
            return _POSTGRES_SERVER_DEFAULTS[value]
        except KeyError:
            raise SnakeDialectError(
                f"PostgresDialect does not know how to translate the server_default {value!r} to SQL"
            ) from None


_PG_CAST = {int: "integer", float: "double precision", bool: "boolean"}
"""What a declared type becomes in a Postgres cast. `str` is absent on purpose: `->>` already gives
text, and casting it would put `::text` on every statement to say nothing."""
