"""The Protocol that defines a SQL dialect (how the SQL is WRITTEN)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from snakeorm.dialects.capabilities import (
    SnakeCapabilities,
    SnakeLimits,
    SnakeSyntax,
)
from snakeorm.expressions.scalar import SnakeFunc
from snakeorm.metadata import (
    SnakeIndexMethod,
    SnakeServerDefault,
    SnakeTypeParams,
)


@runtime_checkable
class SnakeDialect(Protocol):
    """How the SQL is written for one specific engine. It executes NOTHING.

    It only enters `sql/` (emission). The graph and the models are 100% engine-agnostic.
    Adding a new engine = one implementation of this Protocol, without touching the core.
    """

    capabilities: SnakeCapabilities
    """What the engine KNOWS how to do, answered against the WHOLE `Cap` catalogue. The source of truth.

    It is one object and not twenty loose attributes for two reasons the attributes could not give:
    it can be WALKED (that is where the startup warning comes from, one for each thing the engine
    does not give) and it can say "halfway" (SQLite stores an exact `Decimal` and sorts it as text:
    neither absent nor full).
    """
    syntax: SnakeSyntax
    """Differences in the SHAPE of the statement. They are translated in the emitter; they never stop the plan."""
    limits: SnakeLimits
    """The engine's numeric ceilings. `None` is not "no ceiling": it is "it ignores the declared parameter"."""

    # The same old `supports_*`, `triggers_are_table_scoped` and `max_*` still exist as READ-ONLY
    # properties derived from the three objects above, so the reads already written all over the
    # package keep working while they migrate. `DerivedFlags` implements them. Declared as
    # properties and not as attributes on purpose: a plain attribute DOES satisfy a read-only
    # property in a Protocol, so a dialect can use either of the two forms; the other way round it
    # cannot.

    @property
    def supports_returning(self) -> bool:
        """Whether it can return the rows it wrote (`INSERT ... RETURNING`)."""
        ...

    @property
    def supports_row_constructor(self) -> bool:
        """Whether it understands `(a, b) IN ((...), (...))`. If not, the emitter uses the equivalent OR-of-ANDs."""
        ...

    @property
    def supports_transactional_ddl(self) -> bool:
        """Whether DDL goes inside the transaction. With it, an N-step migration is all-or-nothing."""
        ...

    @property
    def supports_upsert(self) -> bool:
        """Whether it can do an INSERT that is idempotent on conflict. Without it, `session.upsert()` raises (it does not emulate: there is a race)."""
        ...

    @property
    def supports_add_constraint(self) -> bool:
        """Whether it accepts `ALTER TABLE ... ADD CONSTRAINT`. It decides the SHAPE of the plan: with
        it the FKs go AT THE END with no ordering between tables; without it (SQLite) they go INSIDE the CREATE TABLE and force a topological order."""
        ...

    @property
    def supports_alter_column(self) -> bool:
        """Whether it can change a column's type/nullability/default. SQLite cannot: it would require rebuilding the table."""
        ...

    @property
    def supports_schemas(self) -> bool:
        """Whether it has named schemas (`CREATE SCHEMA`). On SQLite the "schemas" are ATTACHed databases (`ATTACH`)."""
        ...

    @property
    def supports_stored_functions(self) -> bool:
        """Whether it stores named functions that a migration can create.

        A capability of its OWN ever since the catalogue exists. The plan used to ask about
        `supports_schemas` to decide whether it could create a function: it matched on all three
        engines, so it worked and nobody saw it, but they are different things and a new engine
        would have inherited the confusion.
        """
        ...

    @property
    def supports_row_locking(self) -> bool:
        """Whether it can lock ROWS (`SELECT ... FOR UPDATE`). SQLite locks the file: asking for it fails at compile time."""
        ...

    @property
    def supports_comments(self) -> bool:
        """Whether it STORES table and column comments. Only SQLite does not.

        Not "whether it has `COMMENT ON`": MySQL has no such statement and stores comments all the
        same, as a clause. The spelling lives in `syntax.comment_style`.
        """
        ...

    @property
    def supports_replace_view(self) -> bool:
        """Whether it can do `CREATE OR REPLACE VIEW`. Without it, altering a view is drop+create, and `realize()` rewrites it."""
        ...

    @property
    def supports_parenthesised_compound(self) -> bool:
        """Whether the branches of a UNION/EXCEPT/INTERSECT may go in PARENTHESES. It is not cosmetic:
        the parentheses make a `LIMIT` belong to the branch and not to the whole set. SQLite rejects them."""
        ...

    @property
    def supports_cte_in_compound_branch(self) -> bool:
        """Whether a `WITH [RECURSIVE] ...` may be a BRANCH of a UNION/EXCEPT/INTERSECT.

        A different question from `supports_parenthesised_compound`, and the two only look alike from
        Postgres: MySQL parenthesises branches and still refuses a CTE inside one."""
        ...

    @property
    def supports_ilike(self) -> bool:
        """Whether it has `ILIKE`. Without it (SQLite) the emission falls back to `LOWER(a) LIKE LOWER(b)`, with ASCII-only folding."""
        ...

    @property
    def triggers_are_table_scoped(self) -> bool:
        """Whether a trigger belongs to a TABLE (`DROP TRIGGER x ON t`) or is global (SQLite: `DROP TRIGGER x`).
        Different syntax, not an absent capability: it is translated in the emitter, the plan does not stop."""
        ...

    @property
    def max_bind_params(self) -> int:
        """Ceiling of placeholders per statement; the bulk INSERT slices into batches with it. Postgres: 65535."""
        ...

    @property
    def max_numeric_precision(self) -> int | None:
        """TOTAL digits a NUMERIC/DECIMAL accepts. Postgres: 1000. MySQL: 65.
        `None` if the engine does not restrict it because it IGNORES the declared parameter (SQLite,
        which has per-column affinity): there, any number would assert a limit that does not exist."""
        ...

    @property
    def max_numeric_scale(self) -> int | None:
        """Decimal places a NUMERIC/DECIMAL accepts. It is NOT the same number as the precision: MySQL
        stops at 30 with a precision of 65, so `DECIMAL(40,35)` has one valid half and one that is not."""
        ...

    @property
    def max_fractional_seconds(self) -> int | None:
        """Fractional-second digits of a date column. Postgres and MySQL: 6 (microseconds, the
        resolution of Python's `datetime`). SQL Server reaches 7 and Oracle 9 — that is why the
        number belongs to the engine and not to the model."""
        ...

    def placeholder(self, index: int) -> str:
        """Returns the parameter marker for the given position (e.g. '%s', '$1', '?')."""
        ...

    def trigger_statements(self, name: str, body: str) -> tuple[list[str], str]:
        """How this engine spells a trigger body: `(statements to run first, the body to inline)`.

        THE THREE ARE DIFFERENT FROM EACH OTHER, which is why this is a translation and not a flag.
        Measured, all three:

            PostgreSQL   the body goes in a FUNCTION and the trigger calls it (`EXECUTE FUNCTION f()`)
            SQLite       the body goes between `BEGIN` and `END`; without them it is a syntax error
            MySQL        a single statement goes bare

        Sending it through verbatim made a declaration fail on whichever engine was not the one it
        had been written for, and the DRIVER is what said so — `syntax error at or near "UPDATE"` on
        PostgreSQL, `near "UPDATE": syntax error` on SQLite. Two different complaints about the same
        portable declaration.

        The first return value is anything that must exist BEFORE the trigger (PostgreSQL's function,
        nothing for the others); the second is what goes after `FOR EACH ROW`.
        """
        ...

    def quote_ident(self, name: str) -> str:
        """Quotes an identifier (table or column) the way the engine wants it."""
        ...

    def json_get_sql(
        self, source: str, key_path: tuple[str, ...], as_type: type
    ) -> str:
        """Emits a read INSIDE a JSON document, cast to the declared type.

        `source` arrives already emitted (a quoted column, or an expression). The three engines spell
        this so differently —`->>` and a `{a,b}` path, `JSON_EXTRACT` with `$.a` and an unquote, a
        bare `json_extract`— that it belongs here for the same reason placeholders do: what the SQL
        SAYS is the dialect's business, what it MEANS is the graph's.

        The path is emitted INSIDE a literal because no engine takes a placeholder there. The keys
        are validated when the expression is BUILT (`SnakeValue.json_get`), which is why this may
        interpolate them.
        """
        ...

    def date_shift_sql(
        self, source: str, amount_placeholder: str, unit: str, keeps_time: bool
    ) -> str:
        """Emits a date moved by a signed amount, with the amount as a PARAMETER.

        The clearest case in the ORM for this seam: the three spellings have nothing in common
        (`+ INTERVAL`, `DATE_ADD`, a modifier string), and all three were measured to accept the
        amount as a placeholder, so the rule that values never touch the statement survives.

        `unit` arrives as the agnostic lowercase name (`day`, `month`); each dialect shapes it.
        `keeps_time` says whether the source carries a clock, which only SQLite needs — it has no
        date type to inspect, and picking `date()` for a timestamp would silently drop the time.
        """
        ...

    def string_agg_sql(
        self, value: str, separator: str, order_by: str, params: list[object]
    ) -> str:
        """Emits a group joined into one string, deciding how the SEPARATOR travels.

        It takes `params` for the same reason `limit_offset` does: whether the separator can be a
        placeholder is the ENGINE's answer, not the emitter's. Measured — PostgreSQL and SQLite take
        it as a normal argument and parameterise it; MySQL makes it the `SEPARATOR` keyword and
        rejects a placeholder there, so that dialect escapes it through `literal()`.

        `order_by` arrives already emitted, or empty. It is worth passing whenever a person reads the
        result: without it the order belongs to the engine and can change between runs.
        """
        ...

    def integer_division_op(self) -> str:
        """How this engine spells division between two INTEGERS.

        MEASURED, and the three do not agree: `SELECT 45/50` answers `0` on PostgreSQL and SQLite and
        `0.9000` on MySQL, whose `/` is decimal division and which keeps `DIV` as a separate operator
        for the integer one. The ORM declares `SnakeArith[int]` for two integer columns, so without
        this the declared type is simply false on one engine of three.

        It is asked ONLY when both operands are provably integers. Anything unproven keeps `/`.
        """
        ...

    def cast_sql(self, source: str, as_type: type) -> str:
        """Emits an EXPLICIT cast of an already-emitted value to the named type.

        It lives here for the same reason `json_get_sql` does, and the reason was MEASURED rather
        than assumed: `CAST(x AS NUMERIC)` answers `0.9` on PostgreSQL and `0` on SQLite, whose
        NUMERIC affinity collapses an integral value back to an integer. A single spelling shared by
        the three engines would be right on two and silently wrong on the third.

        The type is guaranteed to be in `CASTABLE`: `snake_cast` refuses anything else at the call
        site, so an implementation never has to answer for a type it cannot spell.
        """
        ...

    def map_type(
        self,
        python_type: object,
        autoincrement: bool = False,
        params: SnakeTypeParams | None = None,
    ) -> str:
        """Translates a Python type into its COMPLETE SQL type, with its family's parameters.

        `params` arrives as ONE object per family (an int's width, a str's length, a Decimal's
        precision, a dict's backing) and not as five loose knobs: loose, `precision` ended up
        OUTSIDE this method —it was concatenated onto the result with an f-string— and that is why
        it was the only parameter that was never validated. What this returns is the whole type,
        not a fragment.

        Returning the complete type is also what lets each engine genuinely decide: Postgres honours
        every parameter, SQLite ignores the ones it does not distinguish.
        """
        ...

    def drop_all_sql(self, tables: Sequence[str]) -> tuple[str, ...]:
        """Statements that leave the schema empty of `tables`, in the order they must run.

        Emptying a schema is DDL, so it is written here like the rest of it. The keyword was never
        the hard part: what differs is how each engine is persuaded to ignore the foreign keys while
        the tables come down — Postgres cascades per statement, MySQL has a session switch, SQLite
        has a pragma. Three answers to one question is what a dialect is for.

        It lives in the Protocol so a fourth engine cannot arrive without answering it. The CLI's
        `fresh` used to write `DROP TABLE ... CASCADE` itself, which is Postgres and only Postgres,
        so the one DESTRUCTIVE command failed halfway on the other two.

        Empty in, empty out: with no tables there is nothing to bracket either.
        """
        ...

    def explain_sql(self, sql: str) -> str:
        """Wraps a statement so the engine reports its PLAN instead of running it.

        It lives here and not in the driver because the difference is grammar, not execution:
        `EXPLAIN` on two engines, `EXPLAIN QUERY PLAN` on SQLite. The compiled `(sql, params)` goes
        down the existing `fetch_all`, so nothing in the driver Protocol moves for this.

        The ANSWER has no common shape and is not given one: Postgres returns one column, SQLite
        four, MySQL about a dozen. The session hands back the engine's own lines.
        """
        ...

    def statement_timeout_sql(self, milliseconds: int) -> str | None:
        """The statement that caps how long a query may run, or `None` if the engine has none.

        One hung query drains a pool, so this is a production knob rather than a nicety — and it
        was written INSIDE `TimeoutDriver` as `SET statement_timeout = <ms>`, which is Postgres and
        only Postgres, under a class name that promises nothing about engines. Measured: MySQL
        answers `1193 Unknown system variable` and SQLite a syntax error.

        `None` is a legitimate answer and not a gap: SQLite has no server-side statement timeout at
        all. The caller refuses out loud rather than pretending; inventing something plausible there
        would be answering a different question.

        The value is in MILLISECONDS because that is the unit the API is written in. An engine whose
        variable expects another unit converts here, which is exactly the kind of thing a dialect is
        for.
        """
        ...

    def register_type(self, python_type: object, sql_type: str) -> None:
        """Adds (or rewrites) the SQL spelling of a Python type in THIS dialect.

        The extension point of the type vocabulary: without it, declaring an `INET`, a `CITEXT` or a
        domain type meant editing the dialect — the type system was the single source of truth but
        you could not add words to it. It is per dialect because the same Python type is written
        differently on each engine.
        """
        ...

    def literal(self, value: object) -> str:
        """Formats a value as a SQL literal for DDL (DEFAULT), which takes no placeholders.
        The formatting (TRUE vs 1, quoting) varies between engines, which is why it lives in the dialect.
        """
        ...

    def function_name(self, func: SnakeFunc) -> str:
        """Translates the agnostic name of a scalar function into the engine's own."""
        ...

    def index_method(self, method: SnakeIndexMethod) -> str:
        """Translates an index's access method (agnostic) into the engine's jargon."""
        ...

    def server_default_sql(self, value: SnakeServerDefault) -> str:
        """Translates a SERVER-side default value (agnostic: `NOW`, `UUID_V4`...) into its SQL
        expression on the engine. If it cannot translate it, it raises `SnakeDialectError`.
        """
        ...

    def limit_offset(
        self, limit: int | None, offset: int | None, params: list[object]
    ) -> str:
        """Emits the parametrised LIMIT/OFFSET clause (appending to `params`), or '' if there is neither.
        Non-standard syntax: that is why the dialect decides it.
        """
        ...

    def on_conflict_clause(
        self, conflict_columns: Sequence[str], update_columns: Sequence[str]
    ) -> str:
        """An upsert's conflict-resolution clause. `conflict_columns` define the conflict (a
        UNIQUE/PK constraint); `update_columns` are rewritten with the incoming value, or empty → leave alone.
        """
        ...
