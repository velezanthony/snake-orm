"""The BASE catalogue of capabilities: everything any engine can do, and what each one answers.

Three pieces and not one flat `bool` per capability, because a `bool` cannot do two things:

- **Be walked.** Warning at startup about everything the user's engine does not give them means
  ITERATING the capabilities.
- **Say "halfway".** SQLite stores a `Decimal` and returns it exact, but it sorts it as TEXT
  (`'9.99' > '10.00'`). Neither absent nor full.

Hence `Cap` (the catalogue), `Support` (tri-state with a reason) and `SnakeCapabilities`, which
forces every engine to answer the WHOLE catalogue — unlike a `frozenset` of supported capabilities,
where the one you forgot to declare is simply not there, and "not there" reads as "not supported".
A silent default, in the ORM that shouts. Here one goes missing and it does not start.

Mind the boundary: this is what the engine KNOWS HOW TO DO. The SHAPE of the statement
(`DROP INDEX x` vs `DROP INDEX x ON t`) is not a capability —both engines drop indexes— and lives in
`SnakeSyntax`, which is translated in the emitter and never stops the plan.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from types import MappingProxyType

from snakeorm.core.exceptions import SnakeDialectError


class Cap(Enum):
    """Everything an engine CAN do. Adding a member forces all three dialects to answer.

    Two families, and the distinction matters because the plan treats them differently:

    - The **structural** ones decide whether an operation can be executed. If they are missing, the
      ORM stops and shouts.
    - The **type-fidelity** ones never stop anything: the type is stored all the same (falling back
      to TEXT if it has to) and the value comes back exact. What gets degraded is the SQL SEMANTICS
      —sorting, comparing, operating— and startup warns about that.
    """

    # --- Structural: if they are missing, the operation cannot be executed ---
    RETURNING = auto()
    ROW_CONSTRUCTOR = auto()
    TRANSACTIONAL_DDL = auto()
    UPSERT = auto()
    ADD_CONSTRAINT = auto()
    ALTER_COLUMN = auto()
    SCHEMAS = auto()
    STORED_FUNCTIONS = auto()
    ROW_LOCKING = auto()
    SET_ISOLATION = auto()
    TEXT_IN_PRIMARY_KEY = auto()
    COMMENTS = auto()
    REPLACE_VIEW = auto()
    PARENTHESISED_COMPOUND = auto()
    # A `WITH [RECURSIVE] ...` used as a BRANCH of a UNION/EXCEPT/INTERSECT. It is STRUCTURAL and it
    # is NOT the same question as `PARENTHESISED_COMPOUND`: MySQL parenthesises branches perfectly
    # well and still answers 1064 to a CTE inside one, so the two flags part company on the middle
    # engine — which is exactly the shape of thing that cannot be inferred from the other.
    CTE_IN_COMPOUND_BRANCH = auto()
    ILIKE = auto()
    INDEX_METHODS = auto()
    # `CREATE INDEX ... WHERE`: the index that only covers the rows matching a condition, which is
    # what makes soft-delete and multi-tenancy affordable. It is STRUCTURAL and not advisory,
    # because it does both things this family does: it changes the SQL that gets written (the
    # `WHERE` is dropped where it does not exist) and it stops the plan when dropping it would
    # change the meaning — a partial UNIQUE widened into a full one forbids rows the domain allows.
    PARTIAL_INDEXES = auto()
    # `ALTER TABLE ... DROP COLUMN` over a column a FOREIGN KEY still holds. It is STRUCTURAL and it
    # is not the same question as `ADD_CONSTRAINT`: MySQL adds and drops constraints perfectly well
    # and still refuses this, because InnoDB needs the index the key sits on (error 1553). Measured
    # on all three, and only ONE says yes — which is why it could never be inferred from how
    # complete an engine looks.
    DROP_COLUMN_CASCADES_FK = auto()

    # --- Type fidelity: they never stop the plan, they only warn about what is lost ---
    DECIMAL_ORDERING = auto()
    TIMESTAMPTZ = auto()
    INTERVAL = auto()
    JSON = auto()
    UUID = auto()
    BOOLEAN = auto()
    INT_WIDTHS = auto()
    ARRAYS = auto()
    FLOAT_SPECIALS = auto()
    # Adding MONTHS or YEARS to a date, which is the only part of date arithmetic a calendar has to
    # interpret. Days, hours, minutes and seconds are a fixed span and the three engines agree on
    # them exactly; the end of a month is where they part. It sits in this family and not the
    # structural one because nothing is refused — the date is computed and comes back, and what
    # differs is WHICH date, which is precisely a semantics warning.
    CALENDAR_INTERVAL = auto()
    # ILIKE is in this family and not among the structural ones, and it was the case that made the
    # distinction worth writing down. Every engine matches without regard to case: what changes is
    # the SPELLING (`syntax.has_ilike`) and how much the folding covers. Declared `Nope` here, it
    # said the engine could not do something it does in fact do — and the reason text gave it away
    # by explaining the fallback.


PLAN_CAPS: frozenset[Cap] = frozenset(
    {
        Cap.RETURNING,
        Cap.ROW_CONSTRUCTOR,
        Cap.TRANSACTIONAL_DDL,
        Cap.UPSERT,
        Cap.ADD_CONSTRAINT,
        Cap.ALTER_COLUMN,
        Cap.SCHEMAS,
        Cap.STORED_FUNCTIONS,
        Cap.ROW_LOCKING,
        Cap.SET_ISOLATION,
        Cap.TEXT_IN_PRIMARY_KEY,
        Cap.COMMENTS,
        Cap.REPLACE_VIEW,
        Cap.PARENTHESISED_COMPOUND,
        Cap.CTE_IN_COMPOUND_BRANCH,
        Cap.PARTIAL_INDEXES,
        Cap.DROP_COLUMN_CASCADES_FK,
    }
)
"""The capabilities SOMEBODY reads to decide: they stop an operation or change the shape of the SQL.

The distinction is not documentation, it is what makes the catalogue checkable. A capability in this
list that nobody reads is dead metadata —the ORM would claim to take it into account and would not—,
and that has already happened twice in this project: `db_comment` was stored without anything
emitting a `COMMENT ON`, and `supports_add_constraint` was declared in all three dialects without a
single reader, while foreign keys simply did not exist on SQLite.
`test_every_plan_capability_has_a_consumer` checks it mechanically, which is the only way that has
worked here.
"""

ADVISORY_CAPS: frozenset[Cap] = frozenset(Cap) - PLAN_CAPS
"""The ones that do NOT change the plan: they are declared in order to WARN.

The type-fidelity ones land here because the model works just the same (the value goes in and comes
out exact) and what is lost is the SQL semantics. And `INDEX_METHODS` too, even though it is not a
type one: the thing that enforces it is the dialect's own `index_method()`, which rejects the method
it does not know instead of emitting a plain index and lying. It is here so that the startup warning
counts it.
"""


@dataclass(frozen=True, slots=True)
class Full:
    """The engine does it, and does it properly. There is nothing to tell the user."""


@dataclass(frozen=True, slots=True)
class Degraded:
    """The engine does it, but lying about something. It WORKS: the plan does not stop, the user
    finds out.

    It is the state of almost everything that falls back to TEXT on SQLite: the value goes in and
    comes out exact, and what is lost is that the engine does not treat it as what it is when
    sorting, comparing or operating.
    """

    reason: str

    def __post_init__(self) -> None:
        """The reason is MANDATORY: it is the text the user reads at startup, not a comment."""
        _demand_reason(self.reason, "Degraded")


@dataclass(frozen=True, slots=True)
class Nope:
    """The engine does not do it. Any operation that needs it stops and the ORM explains why."""

    reason: str

    def __post_init__(self) -> None:
        """Same as in `Degraded`: with no reason, the error would say "cannot be done" and leave you just as lost."""
        _demand_reason(self.reason, "Nope")


Support = Full | Degraded | Nope
"""What an engine answers about a capability. The union (and not a bool plus a string) is what makes
it possible to derive both the plan's decision and the warning from it, with no way for them to
contradict each other."""


def _demand_reason(reason: str, kind: str) -> None:
    """Demands a non-empty reason. It lives on its own so `Degraded` and `Nope` cannot diverge."""
    if not reason.strip():
        raise SnakeDialectError(
            f"{kind}() demands a reason: it is the text shown to the user when the session opens. "
            f"Without it, the warning says that something cannot be done and does not say what to "
            f"do about it."
        )


@dataclass(frozen=True, slots=True)
class SnakeCapabilities:
    """What ONE engine answers to the whole catalogue. Incomplete, it does not get built.

    Exhaustiveness is checked at construction time —that is, when the dialect is imported—, which
    for practical purposes is the same moment a type-checker would fail, and in exchange it allows
    iteration.
    """

    declared: Mapping[Cap, Support]

    def __post_init__(self) -> None:
        """Checks that they are ALL there and freezes the map. Without this, a missing one would read
        as absent.

        No number: it said "all 22" and there were already 23. A count written by hand in prose is a
        copy of the catalogue that nobody updates, and in a module whose job is precisely to stop
        something from going undeclared, it is especially ugly. `Cap` does the counting.
        """
        missing = [cap.name for cap in Cap if cap not in self.declared]
        if missing:
            raise SnakeDialectError(
                f"This dialect does not answer {len(missing)} capability(ies) of the catalogue: "
                f"{', '.join(missing)}. Every engine declares them ALL: an undeclared capability "
                f"would read as unsupported without anyone having decided so."
            )
        object.__setattr__(self, "declared", MappingProxyType(dict(self.declared)))

    def support_for(self, cap: Cap) -> Support:
        """What this engine answers about a capability. Never `None`: the catalogue is complete."""
        return self.declared[cap]

    def can(self, cap: Cap) -> bool:
        """Whether the engine can, even if badly. `Degraded` is a YES: the model works.

        Treating it as a no would forbid a `Decimal` on SQLite, which stores and returns the exact value.
        """
        return not isinstance(self.declared[cap], Nope)

    def caveats(self) -> tuple[tuple[Cap, str], ...]:
        """What the user has to be told: (capability, reason) for everything that is not full.

        In catalogue order, which is stable, so the warning does not dance between runs.
        """
        return tuple(
            (cap, support.reason)
            for cap in Cap
            if isinstance(support := self.declared[cap], (Degraded, Nope))
        )


class EmptyInsertStyle(Enum):
    """How an INSERT with NO values is written, that is, a row that is all defaults.

    It is not a laboratory case: any join or event table whose only field of its own is the
    autoincrement id triggers it. `DEFAULT VALUES` is the standard and MySQL does not have it, so
    until this existed the ORM was writing MySQL something it rejects — and it only showed up when
    seeding against a real server.
    """

    DEFAULT_VALUES = auto()
    """`INSERT INTO t DEFAULT VALUES` (Postgres, SQLite)."""
    EMPTY_ROW = auto()
    """`INSERT INTO t () VALUES ()` (MySQL): empty column list and empty row."""


class AlterColumnStyle(Enum):
    """The SHAPE of an `ALTER TABLE ... ALTER COLUMN`. It is not a capability: it is grammar.

    Postgres and MySQL both change a column's type; they write the statement differently. Filing
    this under capabilities is what left `emit_alter_column` hard-wired to Postgres's shape.
    """

    POSTGRES_TYPE_USING = auto()
    """`ALTER COLUMN c TYPE t USING c::t`, with `SET`/`DROP NOT NULL` in separate statements."""
    MYSQL_MODIFY = auto()
    """`MODIFY COLUMN c t NOT NULL`: a single clause that rewrites the whole definition."""
    UNSUPPORTED = auto()
    """The engine cannot (SQLite: it would require rebuilding the table). The plan stops before emitting."""


class CommentStyle(Enum):
    """How a comment is SPELLED. It is grammar, not capability — the same split as `AlterColumnStyle`.

    Filing it under capabilities is what kept `Cap.COMMENTS` answering `Nope` on MySQL for an engine
    that stores comments perfectly well: the dialect's own reason said "it has no COMMENT ON: MySQL
    comments INLINE", which is a sentence about SYNTAX used to justify a claim about the ENGINE. A
    `db_comment` was dropped on a server that would have kept it, and `AlterTableComment` was refused
    with "there is no comment to change". Spelling one intention differently on each engine is
    literally a dialect's job.
    """

    COMMENT_ON = auto()
    """`COMMENT ON TABLE t IS 'x'` (Postgres): a statement of its own, and `IS NULL` removes it."""
    INLINE = auto()
    """MySQL: a CLAUSE, never a statement. `CREATE TABLE ... COMMENT = 'x'` for a new table,
    `ALTER TABLE t COMMENT = 'x'` to change one, and a COLUMN comment only inside the column's own
    definition — which is why changing one alone costs a whole `MODIFY COLUMN`."""
    UNSUPPORTED = auto()
    """The engine stores none (SQLite). `Cap.COMMENTS` is `Nope`, so the plan stops before the
    emitter runs and whatever shape it would have written never reaches a server."""


@dataclass(frozen=True, slots=True)
class SnakeSyntax:
    """SHAPE differences between engines. They are TRANSLATED in the emitter; they never stop the plan.

    Kept apart from the capabilities on purpose. When `triggers_are_table_scoped` lived among the
    `supports_*` it looked like a rare, lonely case, and its sibling for indexes was never written:
    `emit_drop_index` emitted Postgres's shape and broke the rollback of any migration with an index
    on MySQL. With the family declared, the gap is visible.
    """

    triggers_are_table_scoped: bool
    """`DROP TRIGGER x ON t` (Postgres) versus `DROP TRIGGER x` (MySQL and SQLite, without the table).

    It used to put MySQL in the first group while `mysql.py` itself declares it `False`, with a
    comment right next to it saying the opposite. The code was right; the prose explaining it was
    lying, which is the worst combination: whoever reads the attribute in order to write a new
    dialect trusts what is here.
    """
    indexes_are_table_scoped: bool
    """`DROP INDEX x ON t` (MySQL) versus `DROP INDEX x` (Postgres, SQLite)."""
    alter_column_style: AlterColumnStyle
    """How the change of an existing column is written."""
    empty_insert_style: EmptyInsertStyle
    """How an INSERT of a row that is all default values is written."""
    comment_style: CommentStyle
    """How a table's and a column's comment are spelled: a statement of their own, or a clause."""
    defer_constraints_statement: str | None = None
    """How this engine is told to postpone foreign key checking until the COMMIT, or `None`.

    Only an engine that has to REMAKE a table to change a constraint needs it: mid-rebuild the old
    table is dropped, and any key pointing at it is violated at that instant even though the table
    comes back three statements later. Deferring moves the verdict to the COMMIT, where it is the
    ENGINE that answers — so nothing is switched off and nothing is checked by a statement whose
    rows nobody reads.

    `None` on Postgres and MySQL, and not because they lack the feature: they can change a
    constraint in place, so there is no window to hold open. Declaring it here rather than writing
    the pragma into the emitter is what keeps a second engine without `ADD CONSTRAINT` from
    inheriting SQLite's spelling.
    """
    has_nulls_ordering: bool = False
    """Whether the engine spells `ORDER BY x ASC NULLS LAST`, or needs the portable form.

    A SHAPE difference, and it belongs here for the same reason `has_ilike` does: all three engines
    ORDER nulls, and what changes is how you ask. Filing it in the catalogue would say an engine
    cannot do something it does — the mistake `Cap.ILIKE` was written to record.

    Measured on both servers this dialect family serves, because `mysql.py` exists partly because it
    "cannot promise what only one of them does": MariaDB 11.8.8 and MySQL 8.4.11 both answer
    `ERROR 1064` to `NULLS LAST`, and both accept `ORDER BY (x IS NULL) ASC, x ASC` — inside a
    UNION as well. So the two agree and the fallback covers them.

    Defaults to `False` so an engine that says nothing gets the portable form that works everywhere,
    rather than a keyword it may not have. Same default, same reason, as its neighbour.
    """
    has_ilike: bool = False
    """Whether the engine spells a case-insensitive match `ILIKE`, or needs the portable fallback.

    A SHAPE difference and it belongs here, not in the catalogue. All three engines DO match without
    regard to case: Postgres with the keyword, the other two through `LOWER(a) LIKE LOWER(b)`, which
    the emitter writes. Nothing is refused and no plan stops.

    It used to be read off `Cap.ILIKE`, and that is what made `Nope` mean two things — see the note
    on `Cap.ILIKE` itself. Defaults to `False` so an engine that says nothing gets the fallback that
    works everywhere, rather than a keyword it may not have.
    """
    round_casts_first_argument_to: str | None = None
    """What `ROUND(x, digits)` has to cast its value to on this engine, or `None` for no cast.

    Postgres has `ROUND(double precision)` and `ROUND(numeric, int)` and NO
    `ROUND(double precision, int)`, so asking a float for decimal places reached the server as
    `function round(double precision, integer) does not exist` — the driver explaining a decision
    this ORM made, which is what the project refuses everywhere else. It was bug #34's open half.

    A SHAPE difference and not a capability, which is why it lives here: all three engines round to
    a digit count, they just do not all spell it the same way. Declaring the target type rather than
    a boolean is what stops the emitter from holding a Postgres spelling for everybody.

    Applied unconditionally when there is a digit count, because the emitter cannot see the
    argument's Python type —`SnakeFuncCall[T]` erases it— and does not need to: on Postgres the cast
    is a no-op for a `numeric` and correct for a `float` or an `int`.
    """


@dataclass(frozen=True, slots=True)
class SnakeLimits:
    """The engine's NUMERIC ceilings. `None` is not "no ceiling": it is "it ignores the declared parameter".

    It is SQLite's answer, which has a per-column affinity and nothing else. Any number would assert
    a limit that does not exist, and a small one would reject models this engine stores just fine.
    """

    bind_params: int
    """Placeholders per statement. The bulk INSERT slices into batches with this. Postgres: 65535."""
    numeric_precision: int | None
    """TOTAL digits of a NUMERIC/DECIMAL. Postgres 1000, MySQL 65."""
    numeric_scale: int | None
    """Decimal places. NOT the same number as the precision: MySQL stops at 30 with a precision of 65."""
    fractional_seconds: int | None
    """Fractional-second digits of a date. Postgres and MySQL 6 (Python's `datetime`)."""


class DerivedFlags:
    """BRIDGE: the same old `supports_*`/`max_*`, derived from the catalogue. It is temporary, on purpose.

    The three objects above are the source of truth, but some forty reads spread over fifteen
    modules are still written as `dialect.supports_upsert`. Migrating them ALL in the same move that
    introduces the catalogue would be a big change where the failure is, on top of that, silent: two
    tables resolve the flag by STRING (`getattr`), so a name that stopped existing would not break
    compilation, only behaviour.

    With this bridge, the catalogue comes in without touching a single one of those reads, and they
    migrate one at a time afterwards. When none are left, this class gets deleted and the dialects
    stop inheriting anything.
    """

    capabilities: SnakeCapabilities
    syntax: SnakeSyntax
    limits: SnakeLimits

    @property
    def supports_returning(self) -> bool:
        """Whether it can return the rows it wrote (`INSERT ... RETURNING`)."""
        return self.capabilities.can(Cap.RETURNING)

    @property
    def supports_row_constructor(self) -> bool:
        """Whether it understands `(a, b) IN ((...), (...))`; if not, the emitter uses the OR-of-ANDs."""
        return self.capabilities.can(Cap.ROW_CONSTRUCTOR)

    @property
    def supports_transactional_ddl(self) -> bool:
        """Whether DDL goes inside the transaction: with it, an N-step migration is all-or-nothing."""
        return self.capabilities.can(Cap.TRANSACTIONAL_DDL)

    @property
    def supports_upsert(self) -> bool:
        """Whether it can do an INSERT that is idempotent on conflict. Without it, `upsert()` raises: emulating it is a race."""
        return self.capabilities.can(Cap.UPSERT)

    @property
    def supports_add_constraint(self) -> bool:
        """Whether it accepts `ALTER TABLE ... ADD CONSTRAINT`. It decides the SHAPE of the migration plan."""
        return self.capabilities.can(Cap.ADD_CONSTRAINT)

    @property
    def supports_alter_column(self) -> bool:
        """Whether it can change the type or nullability of an existing column."""
        return self.capabilities.can(Cap.ALTER_COLUMN)

    @property
    def supports_schemas(self) -> bool:
        """Whether it has named schemas (`CREATE SCHEMA`)."""
        return self.capabilities.can(Cap.SCHEMAS)

    @property
    def supports_stored_functions(self) -> bool:
        """Whether it stores named functions/procedures.

        It is a capability of its OWN, and it was not before: the plan used to ask about
        `supports_schemas` to decide whether it could create a function. It matched on all three
        engines and that is why nobody noticed, but they are different things and the catalogue puts
        it out in the open.
        """
        return self.capabilities.can(Cap.STORED_FUNCTIONS)

    @property
    def supports_row_locking(self) -> bool:
        """Whether it can lock ROWS (`SELECT ... FOR UPDATE`)."""
        return self.capabilities.can(Cap.ROW_LOCKING)

    @property
    def supports_comments(self) -> bool:
        """Whether it STORES table and column comments — not whether it spells them `COMMENT ON`.

        The distinction is the bug this property was read through: MySQL has no `COMMENT ON` and
        keeps comments perfectly well, and answering `False` here dropped a `db_comment` on a server
        that stores it. The spelling is `syntax.comment_style`.
        """
        return self.capabilities.can(Cap.COMMENTS)

    @property
    def supports_replace_view(self) -> bool:
        """Whether it can do `CREATE OR REPLACE VIEW`. Without it, altering a view is drop+create."""
        return self.capabilities.can(Cap.REPLACE_VIEW)

    @property
    def supports_parenthesised_compound(self) -> bool:
        """Whether the branches of a UNION/EXCEPT/INTERSECT accept parentheses (which make the LIMIT belong to the branch)."""
        return self.capabilities.can(Cap.PARENTHESISED_COMPOUND)

    @property
    def supports_cte_in_compound_branch(self) -> bool:
        """Whether a `WITH RECURSIVE` may be a BRANCH of a UNION/EXCEPT/INTERSECT. Only Postgres."""
        return self.capabilities.can(Cap.CTE_IN_COMPOUND_BRANCH)

    @property
    def supports_ilike(self) -> bool:
        """Whether it spells the case-insensitive match `ILIKE`, or needs `LOWER(a) LIKE LOWER(b)`.

        Read off the SYNTAX and no longer off `Cap.ILIKE`, which is the whole of that fix: what the
        emitter needs here is which SHAPE to write, and the catalogue answers a different question —
        how good the result is. Reading one for the other is what let a `Nope` sit on something that
        works.
        """
        return self.syntax.has_ilike

    @property
    def triggers_are_table_scoped(self) -> bool:
        """`DROP TRIGGER x ON t` versus `DROP TRIGGER x`. Grammar, not capability."""
        return self.syntax.triggers_are_table_scoped

    @property
    def max_bind_params(self) -> int:
        """Ceiling of placeholders per statement."""
        return self.limits.bind_params

    @property
    def max_numeric_precision(self) -> int | None:
        """Total digits of a NUMERIC/DECIMAL, or `None` if the engine ignores the parameter."""
        return self.limits.numeric_precision

    @property
    def max_numeric_scale(self) -> int | None:
        """Decimal places of a NUMERIC/DECIMAL, or `None`."""
        return self.limits.numeric_scale

    @property
    def max_fractional_seconds(self) -> int | None:
        """Fractional-second digits of a date, or `None`."""
        return self.limits.fractional_seconds
