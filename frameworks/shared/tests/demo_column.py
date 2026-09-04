"""The roadmap's *demo* column, computed from the demos themselves.

Four tiers, and the scale is written in the roadmap beside the other three:

    -    the demo layer does not touch it
    *    it lives in the shared domain and NO route opens a door to it
    **   a route reaches it in one or two demos
    ***  a route reaches it in the THREE, so React — which consumes the three APIs — reaches it too

The `**` tier is expected to be EMPTY most of the time and that is a property of the architecture
rather than an accident: the three demos share one query layer, so a feature a route can reach is
normally reachable from all three at once. A `**` means one demo grew a door the others did not,
which is worth seeing.
"""

from __future__ import annotations

import re

from shared.tests.demo_reach import DEMOS, REACH, SHARED

_DERIVABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def symbols_of(row: str) -> tuple[str, ...] | None:
    """The names that give a feature away in demo code, or `None` when nothing can.

    Most rows carry their own symbol in backticks; the rest are DECLARED below, because a row whose
    symbol had to be guessed is a cell that would quietly measure the wrong thing.
    """
    if row in _DECLARED:
        return _DECLARED[row]
    found = tuple(
        item.strip().rstrip("()")
        for item in re.findall(r"`([^`]+)`", row)
        if _DERIVABLE.fullmatch(item.strip().rstrip("()"))
    )
    return found or None


_DECLARED: dict[str, tuple[str, ...] | None] = {
    # -- The graph CAN see these; the row name just does not spell them ---------------------------
    "typed deep navigation (`A.b.c.d`)": None,
    "correlated scalar subquery": ("as_scalar",),
    "`WITH RECURSIVE`": ("recursive",),
    "`@dataclass_transform` on `@snake_model`": ("snake_model",),
    "polymorphic inheritance": ("snake_discriminator",),
    "views (`@snake_view`)": ("snake_view",),
    "signals and triggers": ("snake_on", "CreateTrigger"),
    "indexes and constraints": (
        "SnakeIndex",
        "snake_indexes",
        "snake_check",
        "snake_checks",
    ),
    "index advisor": ("index_hints_from_records", "unindexed_foreign_keys"),
    "WSGI / ASGI / Django contrib": (
        "SnakeDebugWSGI",
        "SnakeDebugASGI",
        "SnakeDebugMiddleware",
    ),
    "model scaffold": ("render_models",),
    "drift detection against the live DB": ("drift",),
    "PostgreSQL introspection": ("PostgresIntrospector",),
    "MySQL introspection": ("MySQLIntrospector",),
    "SQLite introspection": ("SQLiteIntrospector",),
    "runner (atomic per migration)": ("MigrationRunner",),
    "cross-app dependencies": ("depends_on",),
    "statement timeout": ("TimeoutDriver",),
    "logging driver": ("LoggingDriver",),
    "synchronous drivers (psycopg2, PyMySQL, sqlite3)": (
        "PsycopgDriver",
        "PyMySQLDriver",
        "SQLiteDriver",
    ),
    # Named by the FACTORY and not by the class: the demos build these through
    # `SnakeConnectionConfig`, which is the whole point of that class — a driver joined to another
    # engine's dialect is not expressible, so nothing downstream ever writes the driver's name.
    "asynchronous drivers (native psycopg 3 + two on a thread)": (
        "open_session_async",
        "async_session_over",
        "AsyncSession",
    ),
    "connection pool (`pre_ping`, `recycle`, timeout)": (
        "make_async_pool",
        "AsyncSnakePool",
        "psycopg_pool",
    ),
    # -- Rows whose backticks are SQL KEYWORDS and not the API's names ----------------------------
    #
    # `UNION` is `union()`, `OVER` is `row_number()`. Deriving the symbol from the row title reads
    # the SQL and looks for it in Python, which finds nothing and reports a feature the demos use on
    # every listing as untouched. Measured: `union_` appears in nine demo files while the derived
    # `UNION` appeared in none.
    "`UNION` / `INTERSECT` / `EXCEPT`": ("union", "union_all", "intersect", "except_"),
    "window functions (`OVER`, frame)": (
        "row_number",
        "rank",
        "dense_rank",
        "lag",
        "lead",
    ),
    "`CASE` / `COALESCE` / `NULLIF`": ("snake_case", "snake_coalesce", "snake_nullif"),
    "text functions (`LOWER` `UPPER` `TRIM` `LENGTH` `CONCAT` `SUBSTRING` `REPLACE`)": (
        "snake_lower",
        "snake_upper",
        "snake_trim",
        "snake_length",
        "snake_concat",
        "snake_substring",
        "snake_replace",
    ),
    "date functions (`DATE_TRUNC` `EXTRACT`)": ("snake_date_trunc", "snake_extract"),
    "`ABS` / `ROUND`": ("snake_abs", "snake_round"),
    "`CEIL` / `FLOOR` / `SQRT` / `POWER`": (
        "snake_ceil",
        "snake_floor",
        "snake_sqrt",
        "snake_power",
    ),
    "`ILIKE`": ("istartswith", "icontains", "iendswith"),
    "aggregates (`count` `sum` `avg` `min` `max`)": (
        "count",
        "sum_",
        "avg",
        "min_",
        "max_",
    ),
    "composite `IN` (`snake_keys`)": ("snake_keys",),
    "`EXPLAIN`": ("explain",),
    # The row names the report and the thing you CALL is the collector. `DebugReport` appears only
    # as a return annotation, and the walk reads calls and attributes — so measuring by the row's
    # backticks alone asked about a name no demo can ever invoke.
    "collector and `DebugReport`": ("capture_queries", "DebugReport"),
    "constraint failures (`SnakeIntegrityError`)": ("SnakeIntegrityError",),
    "`RETURNING`": ("add", "upsert"),
    "bulk writes (`bulk`)": ("add_all",),
    # -- The graph structurally CANNOT see these, and the entry point is named instead ------------
    #
    # A feature reached through CONFIGURATION leaves no call to follow. Two families do it, and both
    # are declared with the door they actually come through rather than left to measure as absent —
    # which is what the symbol search does, and it would be wrong every time.
    "PostgreSQL dialect": ("make_dialect",),
    "MySQL / MariaDB dialect": ("make_dialect",),
    "SQLite dialect": ("make_dialect",),
    "`Cap` catalogue (`Full` / `Degraded` / `Nope`)": ("make_dialect",),
    "startup caveat warning": ("SnakeSession", "AsyncSession"),
    "`ssr` channel (HTML panel)": (
        "SnakeDebugWSGI",
        "SnakeDebugASGI",
        "SnakeDebugMiddleware",
    ),
    "`envelope` channel": (
        "SnakeDebugWSGI",
        "SnakeDebugASGI",
        "SnakeDebugMiddleware",
    ),
    "`timing` channel (`Server-Timing`)": (
        "SnakeDebugWSGI",
        "SnakeDebugASGI",
        "SnakeDebugMiddleware",
    ),
    "`sidecar` channel": (
        "SnakeDebugWSGI",
        "SnakeDebugASGI",
        "SnakeDebugMiddleware",
    ),
    "`otel` channel (OTLP spans)": (
        "SnakeDebugWSGI",
        "SnakeDebugASGI",
        "SnakeDebugMiddleware",
    ),
    # -- Genuinely not reachable, and saying so is the point ---------------------------------------
    "JSON operators (containment, path)": None,
    "array operators": None,
    "full-text search": None,
    "server `notices` / `statusmessage`": None,
    "ORM error page": None,
    "DDL emitters × engine (the matrix)": None,
    "CLI (`hunt`, migrations)": None,
    "the CODE that implements it": None,
}
"""Rows whose symbol cannot be read off the name, and why each is what it is.

The three dialects and the capability catalogue come through `make_dialect()`, which reads
`DB_BACKEND` — one variable switching all three demos across the three engines. The debug channels
come through the middleware, which reads `SNAKE_ORM_DEBUG`. Neither leaves a call naming the
feature, so a symbol search reports them absent while the demos exercise them on every request.

`None` means no symbol can honestly stand for the row. That is not a gap in the table: a feature
that does not exist, or one whose subject is the test bench rather than the product, cannot be
reached from a route and the column says `-`.
"""


def tier_of(row: str) -> str:
    """The demo tier of one roadmap row: `-`, `*`, `**` or `***`."""
    symbols = symbols_of(row)
    if not symbols:
        return "-"
    reached = [demo for demo in DEMOS if any(name in REACH[demo] for name in symbols)]
    if len(reached) == len(DEMOS):
        return "***"
    if reached:
        return "**"
    # Written in the domain and behind no door: the tier this column exists to make visible.
    return "*" if any(name in SHARED for name in symbols) else "-"
