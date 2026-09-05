"""SnakeSession: the layer with "colour" that EXECUTES the colourless queries.

It orchestrates a driver (execution) and a dialect (emission): it compiles the query, runs it and
maps the rows to the model. The query NEVER executes, which is why the very same one works for an
AsyncSession.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from types import TracebackType
from typing import Any, TypeVar, cast, overload

from snakeorm.decorators.result import SnakeResult
from snakeorm.debug.collector import timed_mapping
from snakeorm.decorators.row import SnakeRow
from snakeorm.dialects import SnakeDialect
from snakeorm.drivers import SnakeDriver
from snakeorm.core.exceptions import (
    SnakeEmitError,
    SnakeRegistryError,
    SnakeUnsupportedFeature,
)
from snakeorm.expressions import (
    SnakeExpr,
    SnakeValue,
)
from snakeorm.fields import SnakePrefetch, SnakePrefetchHop
from snakeorm.metadata import (
    SnakeRelationshipInfo,
    SnakeTableInfo,
)
from snakeorm.model import SnakeModel
from snakeorm.query import (
    SnakeCompound,
    SnakeJoinedQuery,
    SnakeQuery,
    SnakeRecursive,
)
from snakeorm.registry import SnakeRegistry, registry_of
from snakeorm.session.shared import (
    apply_last_insert_id,
    apply_returned,
    column_name,
    direct_column,
    guard_plain_query,
    guard_set_value,
    insert_values,
    pk_condition,
    table_of,
    table_with_pk,
    update_values,
    warn_bulk_loses_generated_keys,
    warn_reduced_fidelity,
)
from snakeorm.session.guards import (
    _guard_declared_limits,
    guard_can_set_isolation,
    guard_uniform_bulk_columns,
)
from snakeorm.session.isolation import SnakeIsolation
from snakeorm.session.planning import (
    Plan,
    Rows,
    _instantiate,
    _instantiate_all,
    _instantiate_with_compiled,
    compile_segments,
    instantiate_rows_with_includes,
)
from snakeorm.session.planning import (
    plan_annotate,
    plan_call,
    plan_insert,
    plan_raw,
    plan_scalar,
)
from snakeorm.session.planning import parents_per_batch, plan_level, routine_name
from snakeorm.session.planning import project_rows
from snakeorm.session.mapper import hydrate_partial, partial_plan_for
from snakeorm.core.signals import (
    SnakeSignal,
    warn_bulk_skips_signals,
)
from snakeorm.core.signals import (
    emit as emit_signal,
)
from snakeorm.sql import (
    emit_delete,
    emit_insert,
    emit_insert_many,
    emit_select,
    emit_update,
    emit_upsert,
)

T = TypeVar("T")
# The WRITE methods ask for a `SnakeModel`: a `SnakeView` does not inherit from it, so the checker
# rejects it IN THE TYPE (static read-only). The READ ones accept any `T`.
ModelT = TypeVar("ModelT", bound=SnakeModel)
R = TypeVar("R", bound="SnakeResult[Any]")
Row = TypeVar("Row", bound="SnakeRow")
A = TypeVar("A")
B = TypeVar("B")
C = TypeVar("C")
D = TypeVar("D")


class SnakeSession:
    """Runs queries against a driver and maps the results to models."""

    def __init__(
        self,
        driver: SnakeDriver,
        dialect: SnakeDialect,
        *,
        model_registry: SnakeRegistry | None = None,
    ) -> None:
        """The session, and the registry whose models decide which TYPE caveats it mentions.

        `model_registry` defaults to the global one, which is what almost every project has. It
        exists because a project built entirely on `@snake_model(registry=...)` used to open a
        session and hear NOTHING: the advisor enumerated the global registry, found no models, and
        the fidelity caveats — the `Decimal` that SQLite degrades, the timestamps without a zone —
        went unsaid. Structural caveats came out either way; the type ones did not.
        """
        self._driver = driver
        self._dialect = dialect
        self._savepoint_depth = (
            0  # depth of nested savepoints (unique names sp1, sp2...)
        )
        warn_reduced_fidelity(dialect, model_registry)

    @property
    def dialect(self) -> SnakeDialect:
        """This session's dialect, read-only: to ask it what the engine knows how to do.

        Public because there is application code that LEGITIMATELY changes with the engine — the
        demos' seeder inserts row by row where there is no `RETURNING`, because it needs the ids —
        and the alternative was for each of them to sneak in through `session._dialect`. Asking about
        a declared capability is the exact opposite of coupling to an engine: it is not taking for
        granted the one you happen to have.
        """
        return self._dialect

    def __enter__(self) -> SnakeSession:
        """Enters a transaction: it returns the session itself."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Closes the transaction: commit if it came out clean, rollback if there was an exception.

        It does not suppress the exception nor close the connection (the driver is injected; its life
        cycle is carried by whoever created it).
        """
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

    def close(self) -> None:
        """Closes the underlying driver (with a pool, it RETURNS the connection to the pool).

        `__exit__` does NOT call it (the driver is injected), but without this method a connection
        taken out of a pool had no way back.
        """
        self._driver.close()

    def _run_plan(self, plan: Plan[T]) -> T:
        """Runs a plan: the ONLY difference from the async session is the `await` that is not here.

        The plans live in `planning.py`, which is COLOURLESS: it decides which SQL to emit and what
        to do with whatever comes back, without executing. Both sessions consuming the same plan is
        what stops them drifting apart — and they had already drifted: the docstring of
        `AsyncSession.add` swore it shared `plan_insert` with this session when this one was emitting
        on its own.
        """
        rows: Rows = (
            self._driver.fetch_all(plan.sql, plan.params) if plan.needs_rows else []
        )
        if not plan.needs_rows:
            self._driver.execute(plan.sql, plan.params)
        return plan.apply(rows)

    def all(
        self, query: SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T]
    ) -> list[T]:
        """Runs the query and returns every row as an instance of the model.

        It also accepts a COMPOUND (`UNION`/`EXCEPT`/`INTERSECT`) with no separate path: it fulfils
        the same contract as a query (`model`, `has_includes`, `to_sql`).
        """
        return self._run(query)

    def first(
        self, query: SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T]
    ) -> T | None:
        """Runs the query with LIMIT 1 and returns the first instance, or None if there is none."""
        models = self._run(query.limit(1))
        return models[0] if models else None

    def iterate(
        self,
        query: SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T],
        *,
        chunk: int = 1000,
    ) -> Iterator[T]:
        """Walks the result WITHOUT materialising it whole: one instance at a time.

            for invoice in session.iterate(SnakeQuery(Invoice), chunk=500):
                export(invoice)

        `all()` builds a list with ALL the rows before returning the first one; over ten million rows
        that is ten million tuples and ten million objects in memory. Here the engine keeps the
        result (a server-side cursor where there is one) and only `chunk` rows travel at a time. It
        is lazy: nothing is executed until the first row is asked for, so cutting out with a `break`
        does not pay for the rest.

        It does NOT admit `include()` of a to-many nor prefetch, and it RAISES if you ask for one.
        The select-in needs every root to fire its second query and in streaming they do not exist:
        the ways out would be materialising (which defeats this) or one query per row (an N+1). Both
        betray what was asked for, so it is said out loud. The `include()` of a to-ONE does work: it
        travels in the same JOIN.
        """
        if isinstance(query, SnakeQuery):
            self._guard_streamable(query)
        return self._stream(query, chunk)

    @staticmethod
    def _guard_streamable(query: SnakeQuery[T]) -> None:
        """Rejects what streaming cannot serve without degrading into materialising or into an N+1."""
        if query.prefetches():
            raise SnakeUnsupportedFeature(
                "iterate() cannot resolve a prefetch: it chains one query PER LEVEL and needs every "
                "parent of the previous level, which in streaming does not exist yet. Use all() "
                "if the result fits, or walk it in batches with limit/offset."
            )
        if query.to_many_includes():
            raise SnakeUnsupportedFeature(
                "iterate() cannot resolve a to-many include(): the select-in needs ALL the roots to "
                "launch its second query, and here the rows come out one at a time. Serving it "
                "would demand materialising them (which is what you wanted to avoid) or one "
                "query per row (an N+1). Drop the include and load the children separately, or "
                "use all(). A to-one include() DOES work: it rides in the same JOIN."
            )

    def _stream(
        self,
        query: SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T],
        chunk: int,
    ) -> Iterator[T]:
        """The generator of `iterate()`. Split off so the GUARD fires on the call, not on consumption.

        Were this `iterate()` itself, the body would not run until the first `next()` and a
        `session.iterate(query_with_include)` would not raise until somebody walked it — the error
        would show up far from the line that caused it.
        """
        if isinstance(query, SnakeQuery) and query.to_one_includes():
            sql, params = query.to_include_sql(self._dialect)
            # Compiled ONCE, above the loop. Resolving inside it cost three lookups per
            # segment per row, and streaming is precisely where the row count is unbounded.
            compiled = compile_segments(query.include_segments())
            for row in self._driver.fetch_iter(sql, params, chunk=chunk):
                yield cast("T", _instantiate_with_compiled(compiled, row))
            return
        sql, params = query.to_sql(self._dialect)
        model = query.model
        table = registry_of(model).table_of(model)
        assert (
            table is not None
        )  # the query would not have been built without a registered table
        # `only()`/`defer()` narrow the ROW, so the plan has to be narrowed with it — the same
        # question `_map` asks for `all()`, and it was not asked here. The SQL was already right
        # (both paths compile it with the same `to_sql`), so a streamed `only()` emitted three
        # columns and hydrated against four, and the failure surfaced deep in the mapper as a `zip`
        # of unequal lengths that named neither knob. Two read paths over one query may not disagree
        # about what a row IS.
        columns = getattr(query, "projected_columns", None)
        if columns is not None:
            plan, missing = partial_plan_for(model, table, columns)
            for row in self._driver.fetch_iter(sql, params, chunk=chunk):
                yield hydrate_partial(model, plan, missing, row)
            return
        for row in self._driver.fetch_iter(sql, params, chunk=chunk):
            # `_instantiate` and not `hydrate`: it is the only place that decides the concrete class of
            # a polymorphic hierarchy, and calling `hydrate` straight made a streamed read answer with
            # the BASE class while `all()` over the same query answered with the children — and left the
            # siblings' columns on the instance. `_instantiate`'s own docstring lists the paths that
            # inherit the dispatch; this one was missing from the list rather than from the design.
            yield _instantiate(model, table, row)

    def _run(
        self, query: SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T]
    ) -> list[T]:
        """Runs the query: it loads the root (JOINing the to-ones) and then the to-manys separately."""
        # A COMPOUND is dispatched here and leaves (it never has includes). It is checked by type,
        # not by `has_includes`, so the checker narrows to `SnakeQuery` in what follows.
        if isinstance(query, (SnakeCompound, SnakeRecursive)):
            sql, params = query.to_sql(self._dialect)
            return self._map(query, self._driver.fetch_all(sql, params))

        if not query.has_includes:
            sql, params = query.to_sql(self._dialect)
            return self._map(query, self._driver.fetch_all(sql, params))

        if query.to_one_includes():
            sql, params = query.to_include_sql(self._dialect)
            segments = query.include_segments()
            rows = self._driver.fetch_all(sql, params)
            parents = cast("list[T]", instantiate_rows_with_includes(segments, rows))
        else:
            sql, params = query.to_sql(self._dialect)
            parents = self._map(query, self._driver.fetch_all(sql, params))

        parent_table = registry_of(query.model).table_of(query.model)
        assert parent_table is not None
        for relationship in query.to_many_includes():
            self._load_to_many(parents, parent_table, relationship)
        for prefetch in query.prefetches():
            self._run_prefetch(parents, prefetch)
        return parents

    def _run_prefetch(
        self, roots: Sequence[object], prefetch: SnakePrefetch[Any]
    ) -> None:
        """Resolves a nested prefetch chain level by level: ONE query per hop, never an N+1.

        The frontier starts at the roots and advances hop by hop (one level's children are the next
        one's frontier). If it empties out, the chain stops: there are no parents to hang grandchildren on.
        """
        frontier: list[object] = list(roots)
        for hop in prefetch.hops():
            if not frontier:
                break
            frontier = self._load_level(frontier, hop)

    def _load_to_many(
        self,
        parents: Sequence[object],
        parent_table: SnakeTableInfo,
        relationship: SnakeRelationshipInfo,
    ) -> None:
        """Loads a ONE-hop to-many relationship with a select-in and hooks the list onto each parent."""
        if not parents:
            return
        # The PARENT's registry, which the rows themselves carry. `_load_to_many` has no query in
        # scope, and the global registry is the wrong answer for any model with `registry=`.
        child_table, child_model = registry_of(type(parents[0])).resolve_relationship(
            relationship
        )
        assert child_model is not None and child_table is not None
        hop = SnakePrefetchHop(
            name=relationship.name,
            kind=relationship.kind,
            parent_table=parent_table,
            child_model=child_model,
            child_table=child_table,
            relationship=relationship,
        )
        self._load_level(parents, hop)

    def _load_level(
        self, parents: Sequence[object], hop: SnakePrefetchHop
    ) -> list[object]:
        """Runs the plan of ONE level (to-one, to-many or many-to-many), in as many statements as the
        engine's placeholder ceiling needs.

        The dispatch lives here and not in each caller: all three levels are asked for the same way.
        The BATCHING lives here too, and not inside the plan, for the reason the plan exists: it does
        not execute. Keeping it colourless is what lets the synchronous and the asynchronous session
        consume the very same one, and a loop inside it would either give it colour or change the
        contract of all three levels.

        Every parent falls in exactly one batch, so `attach` assigns it its list exactly once.
        """
        loaded: list[object] = []
        size = parents_per_batch(hop, self._dialect)
        for start in range(0, len(parents), size):
            plan = plan_level(parents[start : start + size], hop, self._dialect)
            if plan is None:
                continue
            sql, params, attach = plan
            loaded.extend(attach(self._driver.fetch_all(sql, params)))
        return loaded

    def count(self, query: SnakeQuery[T]) -> int:
        """Counts the rows that match the query (COUNT(*), it honours filters and JOINs)."""
        guard_plain_query(query, "count")
        sql, params = query.to_count_sql(self._dialect)
        return cast(
            "int",
            self._run_plan(
                plan_scalar(sql, params, lambda value: int(cast("int", value)))
            ),
        )

    def exists(self, query: SnakeQuery[T]) -> bool:
        """Tells whether any row matching the query exists (EXISTS)."""
        guard_plain_query(query, "exists")
        sql, params = query.to_exists_sql(self._dialect)
        return cast("bool", self._run_plan(plan_scalar(sql, params, bool)))

    @overload
    def select(
        self, query: SnakeQuery[Any] | SnakeJoinedQuery[Any, Any], c1: SnakeValue[A], /
    ) -> list[tuple[A]]: ...
    @overload
    def select(
        self,
        query: SnakeQuery[Any] | SnakeJoinedQuery[Any, Any],
        c1: SnakeValue[A],
        c2: SnakeValue[B],
        /,
    ) -> list[tuple[A, B]]: ...
    @overload
    def select(
        self,
        query: SnakeQuery[Any] | SnakeJoinedQuery[Any, Any],
        c1: SnakeValue[A],
        c2: SnakeValue[B],
        c3: SnakeValue[C],
        /,
    ) -> list[tuple[A, B, C]]: ...
    @overload
    def select(
        self,
        query: SnakeQuery[Any] | SnakeJoinedQuery[Any, Any],
        c1: SnakeValue[A],
        c2: SnakeValue[B],
        c3: SnakeValue[C],
        c4: SnakeValue[D],
        /,
    ) -> list[tuple[A, B, C, D]]: ...

    def select(
        self,
        query: SnakeQuery[Any] | SnakeJoinedQuery[Any, Any],
        /,
        *columns: SnakeValue[Any],
    ) -> list[tuple[Any, ...]]:
        """Projects concrete columns and/or aggregates: it returns TUPLES (not model instances).

        Partial data does not pretend to be a complete model. Typed up to FOUR values, and a
        fifth is not a looser tuple — there is no overload for it, so it fails the checker
        (overloads); beyond that, `tuple[Any, ...]`.

        It accepts a `SnakeJoinedQuery` (a JOIN onto a collection -> MULTIPLIED rows, one per child),
        which `all`/`first` do NOT accept: hydrating multiplied models is a type error. Each value is
        coerced to the determinable `python_type`; whatever has none (arithmetic, subqueries) passes
        through untouched.
        """
        guard_plain_query(query, "select")
        sql, params = query.to_project_sql(self._dialect, columns)
        # The coercion lives in `planning`, colourless: the SAME decision in both sessions.
        return project_rows(query, columns, self._driver.fetch_all(sql, params))

    def annotate(
        self, query: SnakeQuery[T], result: type[R], /, **aggregates: SnakeValue[Any]
    ) -> list[R]:
        """Annotates each row of the base model with aggregates and wraps it in a typed `@snake_result`.

        It returns `list[R]` with `R` the concrete `@snake_result` (not `list[Any]`): the
        `SnakeResult[Any]` bound captures the real type and forces `result` to be a `@snake_result`.

        The `**aggregates` match by NAME with `result`'s scalar fields (validated BEFORE emitting).
        The scalars are coerced to the type DECLARED in the `@snake_result` (an `avg: float` would
        receive an AVG's `Decimal` without this).

        LIMIT: that the query consults the SAME model the `result` declares is validated at RUNTIME
        (`SnakeEmitError`), not in the checker: it would demand a dependent bound
        `R <: SnakeResult[T]`, and `TypeVar` bounds cannot be generic. See
        `snakeorm/decorators/result.py`.
        """
        sql, params, build = plan_annotate(query, result, self._dialect, aggregates)
        return cast("list[R]", build(self._driver.fetch_all(sql, params)))

    def call(self, name: str, args: Sequence[object], *, into: type[Row]) -> list[Row]:
        """Calls a database FUNCTION that returns rows and hydrates them into a DECLARED shape.

        It emits `SELECT * FROM name(placeholders)` (a `RETURNS TABLE`/`SETOF` function in Postgres).
        The ARGS travel parametrised (user data, which kills injection); the name is a developer's
        identifier and gets emitted as is.

        POSITIONAL mapping onto the `@snake_row` `into`, coercing each column to its DECLARED type.
        OPAQUE SQL: neither the routine's existence nor its shape is checked (you declare, I
        hydrate). For a PROCEDURE with no rows, use `execute_procedure(...)`.
        """
        sql, params, build = plan_call(name, args, into, self._dialect)
        return cast("list[Row]", build(self._driver.fetch_all(sql, params)))

    def explain(self, query: SnakeQuery[ModelT]) -> list[str]:
        """Asks the engine for its PLAN for this query, without running it.

        The dialect wraps the compiled statement and the driver runs it: `EXPLAIN` costs an extra
        round trip and nothing else, and the parameters travel as parameters.

        The lines come back as the ENGINE writes them. Postgres answers one column, SQLite four and
        MySQL about a dozen, so a row is joined into a line rather than forced into a shape the
        three do not share.
        """
        sql, params = query.to_sql(self._dialect)
        rows = self._driver.fetch_all(self._dialect.explain_sql(sql), params)
        return [
            " ".join("" if cell is None else str(cell) for cell in row) for row in rows
        ]

    def raw(
        self, sql: str, params: Sequence[object] = (), *, into: type[Row]
    ) -> list[Row]:
        """Runs RAW SQL and hydrates it into a DECLARED shape (`@snake_row`).

        The escape hatch for the SQL the builder does not cover; at least the result comes back
        TYPED. Parametrised values; the SHAPE is not checked (the same contract as `call`: you
        declare, I hydrate).

        Limit: the number of columns is checked ROW BY ROW, so a query with no rows passes even if
        its shape does not match (the driver hands over data, not the cursor's description). To write
        without reading (`VACUUM`, `SET`), use the driver directly.
        """
        build = plan_raw(into)
        return cast("list[Row]", build(self._driver.fetch_all(sql, tuple(params))))

    def get_or_create(
        self, query: SnakeQuery[ModelT], build: Callable[[], ModelT]
    ) -> tuple[ModelT, bool]:
        """Looks up with the query and, if there is nothing, inserts whatever `build` returns. Gives `(row, created)`.

            user, created = session.get_or_create(
                SnakeQuery(User).filter(User.email == "a@x.com"),
                lambda: User(email="a@x.com", name="Ana"),
            )

        The boolean is the reason it exists: `upsert` writes too, but it does not say whether it
        created it or it was already there. `build` is an explicit CALLABLE (not the filter's magic
        `**kwargs` as in Django): you build the object yourself with the typed constructor.

        Mind the race: another transaction fits between the SELECT and the INSERT. If two processes
        can create the same row, put a UNIQUE on it and catch its violation, or use `upsert`.
        """
        found = self.first(query)
        if found is not None:
            return found, False
        return self.add(build()), True

    def refresh(self, instance: ModelT) -> ModelT:
        """Reloads the instance from the DB, overwriting ALL of its columns. It returns the same one.

        It is needed when the DB changed the row on its own (a trigger, a `server_default`, a bulk
        write, another transaction); the alternative was re-querying and having TWO objects for the
        same row. It is identified by PK; if the row is no longer there, it is said in plain words.
        """
        table = table_with_pk(instance)
        sql, params = emit_select(
            table, self._dialect, where=pk_condition(table, instance)
        )
        rows = self._driver.fetch_all(sql, params)
        if not rows:
            raise SnakeRegistryError(
                f"{type(instance).__name__} could not be refreshed: its row is gone from "
                f"'{table.name}'. Did another transaction delete it?"
            )
        apply_returned(instance, table, rows[0])
        return instance

    def execute_procedure(self, name: str, args: Sequence[object]) -> None:
        """Runs a PROCEDURE that returns NO rows (`CALL name(...)`); the opposite of `call(...)`.

        The ARGS travel parametrised (user data); the NAME is an identifier and cannot, so it goes
        through the same `routine_name` check `call` uses — this door had the very same hole, and
        one rule for the two of them is the point. If your routine returns rows, use `call`.
        """
        checked = routine_name(name)
        placeholders = ", ".join(
            self._dialect.placeholder(index + 1) for index in range(len(args))
        )
        self._driver.execute(f"CALL {checked}({placeholders})", list(args))

    def add(self, instance: ModelT) -> ModelT:
        """Inserts the instance. With RETURNING, it assigns back ALL the columns from the DB.

        Not just the PK: a `DEFAULT now()` or a trigger column comes back into the object (coerced).
        The columns omitted from the INSERT (MISSING, e.g. an autoincrementing PK) are the ones the
        server fills in.
        """
        table = table_of(instance)
        emit_signal(type(instance), SnakeSignal.PRE_SAVE, instance)
        plan = plan_insert(
            instance,
            table,
            self._dialect,
            insert_values(instance, table),
            apply_returned,
        )
        self._run_plan(plan)
        if not self._dialect.supports_returning:
            # Without RETURNING the PK does not come back in the row: it has to be fetched from the
            # driver. It is the only part of the INSERT that does NOT fit in the plan, because the
            # plan is colourless and this asks the connection.
            apply_last_insert_id(instance, table, self._driver)
        emit_signal(type(instance), SnakeSignal.POST_SAVE, instance)
        return instance

    def add_all(self, instances: Sequence[ModelT], /) -> None:
        """Inserts a batch of instances of the SAME model with a single multi-row INSERT per chunk.

        A single `INSERT ... VALUES (...), (...)` (not `executemany`: psycopg2 would go row by row
        with no RETURNING). It chunks by `max_bind_params // columns` so as not to overshoot the
        engine's limit. With RETURNING it fills in the server's columns IN ORDER. An empty list ->
        nothing. Different models -> an error.
        """
        if not instances:
            return
        model = type(instances[0])
        for instance in instances:
            if type(instance) is not model:
                raise SnakeEmitError(
                    "add_all requires every instance to be of the same model; "
                    f"{model.__name__} and {type(instance).__name__} were mixed."
                )
        table = table_of(instances[0])
        # PRE for ALL of them before emitting: a handler can modify the instance, and doing so
        # halfway through the batch would leave some rows with the change and others without it.
        for instance in instances:
            emit_signal(model, SnakeSignal.PRE_SAVE, instance)
        warn_bulk_loses_generated_keys(self._dialect, table)
        rows = [insert_values(instance, table) for instance in instances]
        # Same MODEL is not the same SHAPE: a column with a server default stays out of the
        # constructor, so two instances of one class can carry different sets of values. Once this
        # passes, `rows[0]` answers for all of them BY CONSTRUCTION and the branch below is correct
        # rather than lucky — it used to let the first instance decide, and emit `DEFAULT VALUES`
        # for every one of them while the others' values were computed and thrown away.
        guard_uniform_bulk_columns(rows, model.__name__)
        # An all-defaults batch -> no client values -> `DEFAULT VALUES`, of ONE row (there is no
        # portable all-defaults multi-row). It falls back to one insert per instance, like `add`.
        if not rows[0]:
            for instance in instances:
                sql, params = emit_insert(table, self._dialect, {})
                if self._dialect.supports_returning:
                    apply_returned(
                        instance, table, self._driver.fetch_all(sql, params)[0]
                    )
                else:
                    self._driver.execute(sql, params)
            for instance in instances:
                emit_signal(model, SnakeSignal.POST_SAVE, instance)
            return
        chunk = max(1, self._dialect.max_bind_params // max(1, len(rows[0])))
        for start in range(0, len(instances), chunk):
            batch = instances[start : start + chunk]
            sql, params = emit_insert_many(
                table, self._dialect, rows[start : start + chunk]
            )
            if self._dialect.supports_returning:
                for instance, row in zip(
                    batch, self._driver.fetch_all(sql, params), strict=True
                ):
                    apply_returned(instance, table, row)
            else:
                self._driver.execute(sql, params)
        for instance in instances:
            emit_signal(model, SnakeSignal.POST_SAVE, instance)

    def upsert(
        self,
        instance: SnakeModel,
        /,
        *,
        on_conflict: Sequence[SnakeExpr[Any]],
        update: Sequence[SnakeExpr[Any]] = (),
    ) -> None:
        """Inserts the instance resolving the conflict over `on_conflict` (an idempotent upsert).

        Without `update` -> it does not touch the row (`DO NOTHING`); with `update` -> it rewrites
        those columns (`DO UPDATE SET c = EXCLUDED.c`). The jargon (`ON CONFLICT`) is translated by
        the dialect. A `DO NOTHING` with a conflict returns no row, so there is nothing to assign.

        If the dialect does not support it, `SnakeUnsupportedFeature`: it is NOT emulated with
        SELECT+INSERT (a race between the SELECT and the INSERT; it would fake an atomicity it does
        not have).
        """
        if not self._dialect.supports_upsert:
            raise SnakeUnsupportedFeature(
                "this dialect does not support upsert; it is NOT emulated with SELECT+INSERT "
                "because that emulation has a race condition and would fake an atomicity it "
                "does not have."
            )
        table = table_of(instance)
        emit_signal(type(instance), SnakeSignal.PRE_SAVE, instance)
        sql, params = emit_upsert(
            table,
            self._dialect,
            insert_values(instance, table),
            conflict_columns=[direct_column(column) for column in on_conflict],
            update_columns=[direct_column(column) for column in update],
        )
        if self._dialect.supports_returning:
            rows = self._driver.fetch_all(sql, params)
            if rows:
                apply_returned(instance, table, rows[0])
        else:
            self._driver.execute(sql, params)
        emit_signal(type(instance), SnakeSignal.POST_SAVE, instance)

    def update(self, instance: SnakeModel) -> None:
        """Updates the instance's non-PK columns, filtering by its primary key."""
        table = table_with_pk(instance)
        values = update_values(instance, table)
        emit_signal(type(instance), SnakeSignal.PRE_SAVE, instance)
        sql, params = emit_update(
            table, self._dialect, values, where=pk_condition(table, instance)
        )
        self._driver.execute(sql, params)
        emit_signal(type(instance), SnakeSignal.POST_SAVE, instance)

    def delete(self, instance: SnakeModel) -> None:
        """Deletes the instance's row, filtering by its primary key."""
        table = table_with_pk(instance)
        emit_signal(type(instance), SnakeSignal.PRE_DELETE, instance)
        sql, params = emit_delete(
            table, self._dialect, where=pk_condition(table, instance)
        )
        self._driver.execute(sql, params)
        emit_signal(type(instance), SnakeSignal.POST_DELETE, instance)

    def update_where(
        self,
        query: SnakeQuery[ModelT],
        values: Sequence[tuple[SnakeExpr[Any], object]],
        /,
    ) -> int:
        """Updates IN BULK the rows that match the query's filter. It returns the affected ones.

        `values` are (column, value) pairs: `[(User.views, User.views + 1)]`, with the column as a
        `SnakeExpr` and the value a literal or an expression. It is a SEQUENCE of pairs, NOT a
        `Mapping`, because `SnakeExpr` is deliberately NOT hashable (its `==` returns a condition,
        not a bool).

        The SET only touches columns of the BASE TABLE: navigating a relationship (key or value) is
        rejected (one cannot assign from a joined table without a FROM). Only the WHERE can go deep.
        """
        columns: dict[str, object] = {}
        for column, value in values:
            guard_set_value(value)
            columns[column_name(column)] = value
        # The bulk SET was the ONLY write path that did not check the declared limits, and it is
        # exactly where an out-of-range value does the most damage: it touches N rows at once. The
        # EXPRESSIONS (`views + 1`) are filtered out: their value is computed by the server and there
        # is nothing to measure here.
        table = registry_of(query.model).table_of(query.model)
        assert (
            table is not None
        )  # the query would not have been built without a registered table
        _guard_declared_limits(
            table,
            {
                k: v
                for k, v in columns.items()
                if not isinstance(v, (SnakeValue, SnakeExpr))
            },
        )
        warn_bulk_skips_signals(query.model, "update_where")
        sql, params = query.to_update_sql(self._dialect, columns)
        return self._driver.execute(sql, params)

    def delete_where(self, query: SnakeQuery[ModelT], /) -> int:
        """Deletes IN BULK the rows that match the query's filter. It returns the affected ones.

        The guard lives in the query: with no explicit filter, it raises (a DELETE with no WHERE
        would wipe the table out).
        """
        warn_bulk_skips_signals(query.model, "delete_where")
        sql, params = query.to_delete_sql(self._dialect)
        return self._driver.execute(sql, params)

    def commit(self) -> None:
        """Commits the transaction in progress (it delegates to the driver)."""
        self._driver.commit()

    def rollback(self) -> None:
        """Rolls back the transaction in progress (it delegates to the driver)."""
        self._driver.rollback()

    def set_isolation(self, level: SnakeIsolation) -> None:
        """Sets the ISOLATION level of the transaction starting now.

        The other half of concurrency control: `for_update()` says which rows you RESERVE, the
        isolation what you SEE meanwhile. It has to be called before reading or writing: `SET
        TRANSACTION` is only valid as the first statement, and the engine rejects it if the DB has
        already been touched.

        The engine is ASKED first. This used to hand the statement straight to the driver, so on an
        engine without it the ORM emitted SQL the engine refuses — `near "SET": syntax error` on
        SQLite — instead of saying what it could not do. Emitting for one engine from the session is
        also the thing the dialect seam exists to prevent.
        """
        guard_can_set_isolation(self._dialect)
        self._driver.execute(f"SET TRANSACTION ISOLATION LEVEL {level.value}", ())

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        """SAVEPOINT context manager: it isolates a block inside the transaction in progress.

        On entry `SAVEPOINT`; on a clean exit `RELEASE`; if the block raises, `ROLLBACK TO SAVEPOINT`
        (it discards ONLY what is inside, the transaction stays alive) and RE-RAISES. It exists so a
        long process does not lose everything if one part of it fails.

        NESTABLE: each level uses a name unique per depth (`sp1`, `sp2`, ...; an INTERNAL name, never
        user data). On exit it is decremented, so the same level reuses the name.
        """
        self._savepoint_depth += 1
        name = f"sp{self._savepoint_depth}"
        self._driver.savepoint(name)
        try:
            yield
        except Exception:
            self._driver.rollback_to_savepoint(
                name
            )  # discards the block and leaves what came before untouched
            raise
        else:
            self._driver.release_savepoint(name)  # happy path: consolidates savepoint
        finally:
            self._savepoint_depth -= 1

    def _map(
        self,
        query: SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T],
        rows: list[tuple[object, ...]],
    ) -> list[T]:
        """Maps the raw rows to instances of the query's model. See `map_rows`, which does the work."""
        return map_rows(query, rows)


@timed_mapping
def map_rows(
    query: SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T],
    rows: list[tuple[object, ...]],
) -> list[T]:
    """Maps the raw rows of a query to instances of its model, NARROWED if the query narrowed them.

    A MODULE-LEVEL FUNCTION AND NOT A METHOD, because it never was one: nothing in this body reads
    the session — not the driver, not the dialect — and the only reason it lived on the class was
    that the class is where it was first needed. Leaving it there cost the asynchronous session,
    which cannot inherit it: it wrote the full-row hydration out by hand in three places, so
    `only()` and `defer()` worked on `SnakeSession.all` and raised a `zip()` of unequal lengths on
    `AsyncSession.all`. A decision written once cannot drift; a decision written on one of two
    twins is a promise that the other one will forget it.

    `only()`/`defer()` narrow the row, so the plan has to be narrowed with it. It is asked of the
    query rather than inferred from the row's WIDTH: two columns of the same table can be projected
    in two ways, and counting is how a mapping lines up against the wrong attribute.

    It carries the mapping stopwatch (`@timed_mapping`), and it fits because the rows ARRIVED
    ALREADY: this function never touches the driver, so what it times is hydration and nothing else.
    """
    model = query.model  # out of the loop: a property that was called per row
    table = registry_of(model).table_of(model)
    assert (
        table is not None
    )  # the query would not have been built without a registered table
    columns = getattr(query, "projected_columns", None)
    if columns is not None:
        plan, missing = partial_plan_for(model, table, columns)
        return [hydrate_partial(model, plan, missing, row) for row in rows]
    return _instantiate_all(model, table, rows)
