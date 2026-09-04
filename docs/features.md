# Roadmap — what exists and how well covered it is

This is an INDEX, not a guide: it says what exists and how much net holds it up, never how it works —
that is `docs/users/`' job, and it is not a plan either.

**Scale** — *testing*: `*` the emitted SQL string is asserted · `**` it is EXECUTED and the ROWS are
checked on an engine · `***` on all THREE, or the one that cannot declares it in `Cap`. *contrib*
(`docs/contributors/`) and *user guide* (`docs/users/`): `*` mentioned · `**` section of its own ·
`***` section of its own with a code block. No stars = UNDER CONSTRUCTION · `-` = pending (not
implemented or not written) · `?` = undecided.

**The fourth column, *demo*, and it answers what the other three cannot.** Testing says it is held
up, contrib and the guide say it is written down. None of them says whether **a user of the demos
ever exercises it** — and that is a different question with an uncomfortable answer.

| | *demo* |
|---|---|
| `-` | no demo touches it |
| `*` | it lives in the shared domain and NO route opens a door to it |
| `**` | a route reaches it in one or two of the three |
| `***` | a route reaches it in the THREE, so React — which consumes the three APIs — reaches it too |

It is COMPUTED, not written by hand: `frameworks/shared/tests/demo_column.py` walks the call graph
from every route and module of each demo, and a test asserts this table equals what it finds. A
column kept by hand would be a fifth place to forget.

**Why reachability and not "is it named in this app".** The three demos share one query layer on
purpose — models and selectors written once, each app re-exporting them — so asking whether
`fastapi/apps/` contains `.filter(` measures the architecture rather than the feature, and answers
no for the very reason the design works. That is also why `*` and `**` are usually empty: with the
layer shared, a feature a route can reach is normally reachable from all three at once.

**What `***` means when "all three" is not a sentence.** `on all THREE` reads well for a query and
says nothing for a row whose SUBJECT is one engine, or none. That reading is written down here
because it was rediscovered twice; it is not a lower bar, it is the same bar applied to what the row
is about:

| the row is about | `***` means |
|---|---|
| something the three do | executed on the three, or the one that cannot declares it in `Cap` |
| ONE engine (`SQLite dialect`, `MySQL introspection`, `RebuildTable`) | executed against THAT engine, with what it cannot do declared and asserted |
| no engine at all (the typing, a debug channel) | exercised end to end by the tool that can judge it — mypy AND pyright for the typing, a rendered report for a channel |
| something that does NOT exist (`full-text search`) | a test asserts the ABSENCE, so the day it is implemented the claim goes red instead of quietly staying wrong |

The last row is the one worth keeping: a limit that stays written after it stops being true is the
same kind of lie as a number nobody re-reads.

**No numbers here — the stars are a qualitative level, not a quantity.** `***` does not mean "many
tests", it means all three engines, or the one that cannot declares it in `Cap`. Counts belong to
`coverage`, and the two do not overlap: **`coverage` measures whether a line RAN; the stars measure
WHAT WAS CHECKED.** High coverage next to one star is the dangerous combination — a lot of code
executed and nothing verified — and that is exactly what this table exists to show.

**Every cell is a link, and that is the point of this page.** One claim and its proof, one click
apart. Four directions out of every row:

| the name | *testing* | *contrib* | *user guide* |
|---|---|---|---|
| the CODE that implements it | the TEST that holds it up | the decision | how it is used |

Two rules keep this from rotting. **Anchors, never line numbers** — `page.md#section` survives an
edit, `file.py:694` does not; when a cell points at code it points at the FILE. And **a starred cell
with no link is a lie you can see**: if it claims `**` and cannot point at a page, the star is wrong.
The unlinked ones below are read that way, not as an oversight.

> **`--strict` is not the net for this table.** `mkdocs.yml` excludes `planning/`, so this page is
> never built and its links are never resolved. A deliberately broken link from here left
> `uv run mkdocs build --strict` at **exit 0** and never even appeared in the log; the same broken
> link from `docs/users/reference/limits.md` failed the build at **exit 1**. What holds them is
> `src/test/test_links_the_site_never_builds.py`, one test per link, which covers the three places
> the site never builds: this directory and the two root files.

Where this points: the decisions are in [the architecture](contributors/architecture.md), how to
run the suite is in [testing](contributors/testing.md), the usage is in
[the user guide](users/getting-started/installation.md), and the way in is
[the README](../README.md). The work plans are not in this repository: they are notes for whoever
builds the next thing, they change while they are being executed, and a plan kept beside a shipped
product reads as a promise.

| feature | testing | contrib | user guide | demo |
|---|---|---|---|---|
| **QUERIES** |  |  |  |  |
| [`filter()` / conditions](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.md#filter-and-conditions) | [`***`](users/getting-started/querying.md#filtering) | `***` |
| [`order_by` / `limit` / `offset`](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.md#order-by-limit-offset) | [`***`](users/getting-started/querying.md#ordering-paginating-deduplicating) | `***` |
| [`distinct`](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.md#distinct) | [`***`](users/getting-started/querying.md#ordering-paginating-deduplicating) | `***` |
| [`group_by` / `having`](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.md#group-by-having) | [`***`](users/getting-started/querying.md#projecting-and-aggregating) | `***` |
| [aggregates (`count` `sum` `avg` `min` `max`)](../src/snakeorm/sql/aggregate.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.md#aggregates-count-sum-avg-min-max) | [`***`](users/reference/api/queries.md#aggregates) | `***` |
| [`string_agg`](../src/snakeorm/expressions/functions.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.md#string-agg) | [`***`](users/reference/api/queries.md#aggregates) | `***` |
| [`annotate()`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/internals.md#annotate) | [`***`](users/getting-started/querying.md#projecting-and-aggregating) | `***` |
| [explicit `join()`](../src/snakeorm/sql/joins.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/internals.md#explicit-join) | [`***`](users/guide/relationships.md#joining-a-collection-into-the-projection) | `***` |
| [`include()` (to-one and to-many)](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/architecture.md#relationships-where-the-graph-is-built) | [`***`](users/guide/relationships.md#loading) | `***` |
| [typed deep navigation (`A.b.c.d`)](../src/snakeorm/expressions/paths.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/architecture.md#typing-and-runtime-proxy-the-heart) | [`***`](users/reference/typing.md#the-recursion) | `-` |
| [`.any()` / correlated `exists`](../src/snakeorm/sql/condition.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/internals.md#any-correlated-exists) | [`***`](users/guide/relationships.md#existence) | `***` |
| [correlated scalar subquery](../src/snakeorm/expressions/scalar.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/internals.md#correlated-scalar-subquery) | [`***`](users/guide/advanced-queries.md#scalar-subqueries) | `***` |
| [composite `IN` (`snake_keys`)](../src/snakeorm/expressions/keys.py) | [`***`](../src/test/integration/test_composite_in_e2e.py) | [`***`](contributors/internals.md#composite-in-snake-keys) | [`***`](users/guide/advanced-queries.md#composite-in) | `***` |
| [`only()` / `defer()`](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.md#only-defer) | [`***`](users/getting-started/querying.md#bringing-half-a-row) | `***` |
| [`iterate()` (server cursor)](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_the_composed_stack.py) | [`***`](contributors/internals.md#iterate-server-cursor) | [`***`](users/getting-started/querying.md#walking-a-lot-without-loading-it-all) | `***` |
| [`CASE` / `COALESCE` / `NULLIF`](../src/snakeorm/expressions/conditional.py) | [`***`](../src/test/integration/test_scalar_expressions_e2e.py) | [`***`](contributors/internals.md#case-coalesce-nullif) | [`***`](users/guide/advanced-queries.md#conditional-expressions) | `***` |
| [window functions (`OVER`, frame)](../src/snakeorm/expressions/window.py) | [`***`](../src/test/integration/test_window_e2e.py) | [`***`](contributors/internals.md#window-functions-over-frame) | [`***`](users/guide/advanced-queries.md#window-functions) | `***` |
| [`UNION` / `INTERSECT` / `EXCEPT`](../src/snakeorm/query/compound.py) | [`***`](../src/test/query/test_compound.py) | [`***`](contributors/internals.md#union-intersect-except) | [`***`](users/guide/advanced-queries.md#compound-union-intersect-except) | `***` |
| [`WITH RECURSIVE`](../src/snakeorm/query/recursive.py) | [`***`](../src/test/integration/test_recursive_e2e.py) | [`***`](contributors/internals.md#with-recursive) | [`***`](users/guide/advanced-queries.md#recursive-with-recursive) | `***` |
| [text functions (`LOWER` `UPPER` `TRIM` `LENGTH` `CONCAT` `SUBSTRING` `REPLACE`)](../src/snakeorm/expressions/functions.py) | [`***`](../src/test/integration/test_scalar_expressions_e2e.py) | [`***`](contributors/internals.md#text-functions) | [`***`](users/reference/api/queries.md#text-functions) | `***` |
| [date functions (`DATE_TRUNC` `EXTRACT`)](../src/snakeorm/expressions/functions.py) | [`***`](../src/test/integration/test_date_functions_e2e.py) | [`***`](contributors/internals.md#date-functions) | [`***`](users/reference/api/queries.md#date-functions) | `***` |
| [`ABS` / `ROUND`](../src/snakeorm/expressions/scalar.py) | [`***`](../src/test/integration/test_maths_functions_e2e.py) | [`***`](contributors/internals.md#abs-and-round) | [`***`](users/reference/api/queries.md#rounding-and-magnitude) | `***` |
| [`CEIL` / `FLOOR` / `SQRT` / `POWER`](../src/snakeorm/expressions/scalar.py) | [`***`](../src/test/integration/test_maths_functions_e2e.py) | [`***`](contributors/internals.md#ceil-floor-sqrt-and-power) | [`***`](users/reference/api/queries.md#maths-that-depend-on-the-build) | `***` |
| [`json_get()`](../src/snakeorm/expressions/expression.py) | [`***`](../src/test/integration/test_json_access_e2e.py) | [`***`](contributors/internals.md#json-get) | [`***`](users/getting-started/querying.md#reading-inside-a-json-column) | `***` |
| JSON operators (containment, path) | [`***`](../src/test/test_limits_are_true.py) | [`***`](contributors/internals.md#json-containment-and-path-operators) | [`***`](users/reference/limits.md#what-flat-out-doesnt-exist) | `-` |
| array operators | [`***`](../src/test/test_limits_are_true.py) | [`***`](contributors/internals.md#array-operators) | [`***`](users/reference/limits.md#what-flat-out-doesnt-exist) | `-` |
| full-text search | [`***`](../src/test/test_limits_are_true.py) | [`***`](contributors/internals.md#full-text-search) | [`***`](users/reference/limits.md#what-flat-out-doesnt-exist) | `-` |
| [`ILIKE`](../src/snakeorm/sql/condition.py) | [`***`](../src/test/integration/test_concurrency_controls_e2e.py) | [`***`](contributors/internals.md#ilike) | [`***`](users/getting-started/querying.md#filtering) | `***` |
| [`for_update()` (row locking)](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_concurrency_controls_e2e.py) | [`***`](contributors/internals.md#for-update-row-locking) | [`***`](users/guide/advanced-queries.md#row-locking) | `***` |
| [`raw()`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.md#raw) | [`***`](users/guide/advanced-queries.md#raw-sql) | `-` |
| **WRITES** |  |  |  |  |
| [`insert` / `update` / `delete`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_writes_e2e.py) | [`***`](contributors/internals.md#insert-update-delete) | [`***`](users/getting-started/querying.md#writing) | `***` |
| [`upsert`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_writes_e2e.py) | [`***`](contributors/architecture.md#components) | [`***`](users/getting-started/querying.md#writing) | `***` |
| [bulk writes (`bulk`)](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_writes_e2e.py) | [`***`](contributors/internals.md#bulk-writes) | [`***`](users/getting-started/querying.md#writing) | `***` |
| [`RETURNING`](../src/snakeorm/sql/insert.py) | [`***`](../src/test/scenarios/test_returning_wide.py) | [`***`](contributors/internals.md#returning) | [`***`](users/guide/transactions.md#writes-that-report-what-happened) | `***` |
| [`savepoint()` / `set_isolation()`](../src/snakeorm/session/isolation.py) | [`***`](../src/test/integration/test_concurrency_controls_e2e.py) | [`***`](contributors/internals.md#savepoint-set-isolation) | [`***`](users/guide/transactions.md#savepoints) | `***` |
| [retry on a transient conflict (`with_retry`)](../src/snakeorm/session/retry.py) | [`***`](../src/test/integration/test_retry_e2e.py) | [`***`](contributors/internals.md#with-retry) | [`***`](users/guide/transactions.md#retrying-a-serialization-conflict) | `-` |
| [constraint failures (`SnakeIntegrityError`)](../src/snakeorm/drivers/failures.py) | [`***`](../src/test/integration/test_driver_failures_e2e.py) | [`***`](contributors/internals.md#constraint-failures) | [`***`](users/reference/api/errors.md#constraints) | `-` |
| [`refresh()`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_writes_e2e.py) | [`***`](contributors/internals.md#refresh) | [`***`](users/guide/transactions.md#reloading-from-the-database) | `***` |
| **MODEL AND TYPES** |  |  |  |  |
| [typed descriptors (`SnakeColumn` / `SnakeToOne` / `SnakeToMany`)](../src/snakeorm/fields/typed.py) | [`***`](../src/test/fields/test_typed_specifiers.py) | [`***`](contributors/architecture.md#typing-and-runtime-proxy-the-heart) | [`***`](users/reference/api/models.md#descriptors) | `***` |
| [`@dataclass_transform` on `@snake_model`](../src/snakeorm/decorators/model.py) | [`***`](../src/test/typing/test_type_checkers.py) | `***` | [`***`](users/reference/typing.md#the-constructor) | `***` |
| [COMPOSITE PK and FK](../src/snakeorm/metadata/primary_key.py) | [`***`](../src/test/integration/test_composite_chain_e2e.py) | [`***`](contributors/architecture.md#metadata-pkfk-with-one-structure) | [`***`](users/guide/columns.md#primary-keys) | `-` |
| [polymorphic inheritance](../src/snakeorm/decorators/polymorphic.py) | [`***`](../src/test/integration/test_model_behaviour_e2e.py) | [`***`](contributors/internals.md#polymorphic-inheritance) | [`***`](users/guide/inheritance.md#polymorphic) | `***` |
| [views (`@snake_view`)](../src/snakeorm/decorators/view.py) | [`***`](../src/test/integration/test_compound_as_view.py) | [`***`](contributors/internals.md#views-snake-view) | [`***`](users/reference/api/models.md#model-and-view) | `***` |
| [signals and triggers](../src/snakeorm/core/signals.py) | [`***`](../src/test/integration/test_model_behaviour_e2e.py) | [`***`](contributors/internals.md#signals-and-triggers) | [`***`](users/guide/signals-and-triggers.md) | `-` |
| [indexes and constraints](../src/snakeorm/fields/index.py) | [`***`](../src/test/integration/test_indexes_e2e.py) | [`***`](contributors/internals.md#indexes-and-constraints) | [`***`](users/guide/indexes-and-constraints.md) | `***` |
| [partial indexes](../src/snakeorm/fields/index.py) | [`***`](../src/test/migration/test_partial_indexes_per_engine.py) | [`***`](contributors/internals.md#partial-indexes) | [`***`](users/guide/indexes-and-constraints.md#partial-indexes) | `-` |
| [index methods (`GIN` / `GIST` / `BRIN`)](../src/snakeorm/metadata/index_method.py) | [`***`](../src/test/integration/test_indexes_e2e.py) | [`***`](contributors/internals.md#index-methods-gin-gist-brin) | [`***`](users/guide/indexes-and-constraints.md#index-method) | `-` |
| [comments (`db_comment`)](../src/snakeorm/metadata/table.py) | [`***`](../src/test/migration/test_comments.py) | [`***`](contributors/internals.md#comments-db-comment) | [`***`](users/guide/columns.md#comments) | `-` |
| [type converters (`register_converter`)](../src/snakeorm/core/converters.py) | [`***`](../src/test/integration/test_type_round_trip.py) | [`***`](contributors/internals.md#type-converters-register-converter) | [`***`](users/guide/columns.md#a-type-the-orm-doesnt-ship) | `-` |
| [UTC helpers (`SnakeUtc`, `utc_now`, `to_utc`)](../src/snakeorm/times.py) | [`***`](../src/test/integration/test_utc_helpers_e2e.py) | [`***`](contributors/internals.md#utc-helpers-snakeutc-utc-now-to-utc) | [`***`](users/guide/columns.md#four-helpers-and-why-they-are-not-datetimenow) | `***` |
| **ENGINES** |  |  |  |  |
| [PostgreSQL dialect](../src/snakeorm/dialects/postgres.py) | [`***`](../src/test/integration/test_the_catalogue_does_not_lie.py) | [`***`](contributors/architecture.md#multi-engine-three-axes) | [`***`](users/engines/dialects.md) | `***` |
| [MySQL / MariaDB dialect](../src/snakeorm/dialects/mysql.py) | [`***`](../src/test/integration/test_the_catalogue_does_not_lie.py) | [`***`](contributors/architecture.md#multi-engine-three-axes) | [`***`](users/engines/dialects.md) | `***` |
| [SQLite dialect](../src/snakeorm/dialects/sqlite.py) | [`***`](../src/test/integration/test_the_catalogue_does_not_lie.py) | [`***`](contributors/architecture.md#multi-engine-three-axes) | [`***`](users/engines/dialects.md) | `***` |
| [`Cap` catalogue (`Full` / `Degraded` / `Nope`)](../src/snakeorm/dialects/capabilities.py) | [`***`](../src/test/dialects/test_capabilities.py) | [`***`](contributors/architecture.md#the-capability-catalogue) | [`***`](users/engines/dialects.md#the-capability-catalog) | `***` |
| [startup caveat warning](../src/snakeorm/dialects/capabilities.py) | [`***`](../src/test/integration/test_the_catalogue_does_not_lie.py) | [`***`](contributors/internals.md#startup-caveat-warning) | [`***`](users/engines/dialects.md#how-the-startup-warning-actually-works) | `***` |
| [synchronous drivers (psycopg2, PyMySQL, sqlite3)](../src/snakeorm/drivers/base.py) | [`***`](../src/test/integration/test_the_composed_stack.py) | [`***`](contributors/internals.md#synchronous-drivers) | [`***`](users/getting-started/installation.md#your-engines-driver) | `***` |
| [asynchronous drivers (native psycopg 3 + two on a thread)](../src/snakeorm/drivers/asyncbase.py) | [`***`](../src/test/integration/test_async_session_lifecycle.py) | [`***`](contributors/internals.md#asynchronous-drivers) | [`***`](users/engines/async.md#three-engines-three-async-drivers) | `***` |
| [connection pool (`pre_ping`, `recycle`, timeout)](../src/snakeorm/drivers/pool.py) | [`***`](../src/test/integration/test_the_composed_stack.py) | [`***`](contributors/internals.md#connection-pool) | [`***`](users/engines/multi-connection.md#a-pool-that-survives-a-deploy) | `***` |
| [statement timeout](../src/snakeorm/drivers/timeout.py) | [`***`](../src/test/integration/test_statement_timeout_e2e.py) | [`***`](contributors/internals.md#statement-timeout) | [`***`](users/guide/transactions.md#in-production-wrapping-the-driver) | `-` |
| [logging driver](../src/snakeorm/drivers/logging.py) | [`***`](../src/test/integration/test_the_composed_stack.py) | [`***`](contributors/internals.md#logging-driver) | [`***`](users/guide/transactions.md#in-production-wrapping-the-driver) | `-` |
| server `notices` / `statusmessage` | [`***`](../src/test/test_limits_are_true.py) | [`***`](contributors/architecture.md#where-a-feature-goes-above-the-seam-or-below-it) | [`***`](users/reference/limits.md#what-flat-out-doesnt-exist) | `-` |
| [`EXPLAIN`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_explain_e2e.py) | [`***`](contributors/architecture.md#where-a-feature-goes-above-the-seam-or-below-it) | [`***`](users/guide/debugging.md#asking-the-engine-for-its-plan-explain) | `***` |
| **MIGRATIONS** |  |  |  |  |
| [`diff` and autodetection](../src/snakeorm/migration/autodetect.py) | [`***`](../src/test/integration/test_migration_shapes_e2e.py) | [`***`](contributors/internals.md#diff-and-autodetection) | [`***`](users/getting-started/migrations.md#what-the-autogen-detects) | `-` |
| [runner (atomic per migration)](../src/snakeorm/migration/runner.py) | [`***`](../src/test/migration/test_atomicity.py) | [`***`](contributors/internals.md#runner-atomic-per-migration) | [`***`](users/getting-started/migrations.md#atomicity) | `-` |
| [`RebuildTable` (SQLite's way out)](../src/snakeorm/migration/operations.py) | [`***`](../src/test/integration/test_migration_shapes_e2e.py) | [`***`](contributors/internals.md#rebuildtable-sqlites-way-out) | [`***`](users/reference/api/migrations.md#table-operations) | `-` |
| [`RunPython` (data, with reverse)](../src/snakeorm/migration/operations.py) | [`***`](../src/test/integration/test_migration_cycle_e2e.py) | [`***`](contributors/internals.md#runpython-data-with-reverse) | [`***`](users/getting-started/migrations.md#data-migrations) | `-` |
| [collapsing (`squash`)](../src/snakeorm/migration/squash.py) | [`***`](../src/test/integration/test_migration_shapes_e2e.py) | [`***`](contributors/internals.md#collapsing-squash) | [`***`](users/getting-started/migrations.md#collapsing-the-history) | `-` |
| [cross-app dependencies](../src/snakeorm/migration/loader.py) | [`***`](../src/test/migration/test_loader.py) | [`***`](contributors/internals.md#cross-app-dependencies) | [`***`](users/reference/api/migrations.md#runners) | `-` |
| [DDL emitters × engine (the matrix)](../src/snakeorm/migration/ddl.py) | [`***`](../src/test/migration/test_emitter_dialect_matrix.py) | [`***`](contributors/internals.md#ddl-emitters-by-engine-the-matrix) | [`***`](users/engines/dialects.md#translate-vs-refuse) | `-` |
| **DB-FIRST** |  |  |  |  |
| [PostgreSQL introspection](../src/snakeorm/introspection/postgres.py) | [`***`](../src/test/integration/test_db_first_e2e.py) | [`***`](contributors/internals.md#postgresql-introspection) | [`***`](users/engines/db-first.md#what-it-generates) | `-` |
| [MySQL introspection](../src/snakeorm/introspection/mysql.py) | [`***`](../src/test/integration/test_db_first_e2e.py) | [`***`](contributors/internals.md#mysql-introspection) | [`***`](users/engines/db-first.md#what-it-generates) | `-` |
| [SQLite introspection](../src/snakeorm/introspection/sqlite.py) | [`***`](../src/test/integration/test_db_first_e2e.py) | [`***`](contributors/internals.md#sqlite-introspection) | [`***`](users/engines/db-first.md#what-it-generates) | `-` |
| [model scaffold](../src/snakeorm/introspection/models.py) | [`***`](../src/test/integration/test_db_first_e2e.py) | [`***`](contributors/internals.md#model-scaffold) | [`***`](users/engines/db-first.md#there-is-no-in-place-adoption) | `-` |
| [drift detection against the live DB](../src/snakeorm/introspection/drift.py) | [`***`](../src/test/integration/test_db_first_e2e.py) | [`***`](contributors/internals.md#drift-detection) | [`***`](users/engines/db-first.md#drift-detection) | `-` |
| **DEBUG** |  |  |  |  |
| [collector and `DebugReport`](../src/snakeorm/debug/collector.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.md#collector-and-debugreport) | [`***`](users/guide/debugging.md#inspecting-the-report) | `***` |
| [`ssr` channel (HTML panel)](../src/snakeorm/debug/html.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.md#ssr-channel-html-panel) | [`***`](users/guide/debugging.md#the-channels) | `***` |
| [`envelope` channel](../src/snakeorm/contrib/deliver.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.md#envelope-channel) | [`***`](users/guide/debugging.md#the-envelope-shape) | `***` |
| [`timing` channel (`Server-Timing`)](../src/snakeorm/contrib/deliver.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.md#timing-channel-server-timing) | [`***`](users/guide/debugging.md#the-channels) | `***` |
| [`sidecar` channel](../src/snakeorm/contrib/sidecar.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.md#sidecar-channel) | [`***`](users/guide/debugging.md#the-channels) | `***` |
| [`otel` channel (OTLP spans)](../src/snakeorm/debug/channel.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.md#otel-channel-otlp-spans) | [`***`](users/guide/debugging.md#the-otel-channel-spans-for-a-real-tracer) | `***` |
| [index advisor](../src/snakeorm/advisor.py) | [`***`](../src/test/test_advisor.py) | [`***`](contributors/internals.md#index-advisor) | [`***`](users/guide/indexes-and-constraints.md#which-index-is-missing-snakeorm-advise) | `-` |
| ORM error page | [`***`](../src/test/test_limits_are_true.py) | [`***`](contributors/internals.md#orm-error-page) | [`***`](users/reference/limits.md#what-flat-out-doesnt-exist) | `-` |
| **INTEGRATION** |  |  |  |  |
| [WSGI / ASGI / Django contrib](../src/snakeorm/contrib/wsgi.py) | [`***`](../src/test/integration/test_contrib_middleware_e2e.py) | [`***`](contributors/internals.md#wsgi-asgi-django-contrib) | [`***`](users/guide/debugging.md#plugging-it-into-the-framework-one-line) | `***` |
| [CLI (schema and migrations)](../src/snakeorm/cli/app.py) | [`***`](../src/test/integration/test_cli_three_engines_e2e.py) | [`***`](contributors/internals.md#cli-schema-and-migrations) | [`***`](users/getting-started/migrations.md) | `-` |
