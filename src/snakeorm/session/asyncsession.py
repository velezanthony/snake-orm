"""`AsyncSession`: the same session, awaiting.

It is not a copy of `SnakeSession` with `await` in front: the DECISIONS (which SQL to emit and how to
interpret the rows) live in `planning.py`, colourless, and here they only get executed. Compiler,
dialect, `query/`, `expressions/`, `sql/` and migrations are reused as they are because they do not
execute.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, TypeVar, cast

from snakeorm.dialects import SnakeDialect
from snakeorm.drivers.asyncbase import AsyncDriver
from snakeorm.core.exceptions import (
    SnakeEmitError,
    SnakeRegistryError,
    SnakeUnsupportedFeature,
)
from snakeorm.decorators.result import SnakeResult
from snakeorm.decorators.row import SnakeRow
from snakeorm.expressions import SnakeExpr, SnakeValue
from snakeorm.fields import SnakePrefetch, SnakePrefetchHop
from snakeorm.metadata import SnakeRelationshipInfo, SnakeTableInfo
from snakeorm.model import SnakeModel
from snakeorm.query import (
    SnakeCompound,
    SnakeJoinedQuery,
    SnakeQuery,
    SnakeRecursive,
)
from snakeorm.registry import SnakeRegistry, registry_of
from snakeorm.session.guards import (
    _guard_declared_limits,
    guard_can_set_isolation,
    guard_uniform_bulk_columns,
)
from snakeorm.session.isolation import SnakeIsolation
from snakeorm.session.planning import (
    Plan,
    Rows,
    plan_annotate,
    plan_call,
    plan_insert,
    parents_per_batch,
    plan_level,
    plan_raw,
    plan_scalar,
    project_rows,
    routine_name,
)
from snakeorm.session.mapper import hydrate_partial, partial_plan_for
from snakeorm.session.planning import (
    _instantiate,
    _instantiate_with_compiled,
    compile_segments,
    instantiate_rows_with_includes,
)
from snakeorm.session.session import SnakeSession, map_rows
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
from snakeorm.core.signals import SnakeSignal, warn_bulk_skips_signals
from snakeorm.core.signals import emit as emit_signal
from snakeorm.sql import (
    emit_delete,
    emit_insert,
    emit_insert_many,
    emit_select,
    emit_update,
    emit_upsert,
)

T = TypeVar("T")
ModelT = TypeVar("ModelT", bound=SnakeModel)
Row = TypeVar("Row", bound="SnakeRow")
R = TypeVar("R", bound="SnakeResult[Any]")


class AsyncSession:
    """Runs queries against an `AsyncDriver` and maps the results to models."""

    def __init__(
        self,
        driver: AsyncDriver,
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
        self._savepoint_depth = 0  # depth of nested savepoints (sp1, sp2, ...)
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

    async def __aenter__(self) -> AsyncSession:
        """Enters a transaction: it returns the session itself."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commits if it came out clean, rolls back if there was an exception. It does not close the connection."""
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

    async def _run(self, plan: Plan[T]) -> T:
        """Runs a plan: the ONLY real difference from the synchronous session (the driver's `await`)."""
        rows: Rows = (
            await self._driver.fetch_all(plan.sql, plan.params)
            if plan.needs_rows
            else []
        )
        if not plan.needs_rows:
            await self._driver.execute(plan.sql, plan.params)
        return plan.apply(rows)

    def iterate(
        self,
        query: SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T],
        *,
        chunk: int = 1000,
    ) -> AsyncIterator[T]:
        """Async mirror of `SnakeSession.iterate`: it walks the result without materialising it whole.

            async for invoice in session.iterate(SnakeQuery(Invoice), chunk=500):
                await export(invoice)

        It is NOT `async def`: it returns the iterator so the GUARD fires on the call and not on the
        first `async for`. With the same restriction as the synchronous one: `include()` of a to-many
        and prefetch RAISE, because the select-in needs every root and in streaming they do not exist.
        """
        if isinstance(query, SnakeQuery):
            SnakeSession._guard_streamable(query)
        return self._stream(query, chunk)

    async def _stream(
        self,
        query: SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T],
        chunk: int,
    ) -> AsyncIterator[T]:
        """The generator of `iterate()`. The guard has already passed; here it only hydrates row by row."""
        if isinstance(query, SnakeQuery) and query.to_one_includes():
            sql, params = query.to_include_sql(self._dialect)
            # Compiled ONCE, above the loop. Resolving inside it cost three lookups per
            # segment per row, and streaming is precisely where the row count is unbounded.
            compiled = compile_segments(query.include_segments())
            async for row in self._driver.fetch_iter(sql, params, chunk=chunk):
                yield cast("T", _instantiate_with_compiled(compiled, row))
            return
        sql, params = query.to_sql(self._dialect)
        table = registry_of(query.model).table_of(query.model)
        assert (
            table is not None
        )  # the query would not have been built without a registered table
        # `only()`/`defer()` narrow the ROW, and the plan has to be narrowed with it. The same
        # question the synchronous `_stream` now asks, and it was missing from BOTH of them: the SQL
        # is compiled by one shared `to_sql`, so a narrowed stream emitted the short SELECT and then
        # hydrated against every column of the table. Written out here as well as there because
        # `await` is syntax and one body cannot serve both colours — which is exactly why a fix to
        # one of the two is a demo that works on two frameworks and raises on the third.
        columns = getattr(query, "projected_columns", None)
        if columns is not None:
            plan, missing = partial_plan_for(query.model, table, columns)
            async for row in self._driver.fetch_iter(sql, params, chunk=chunk):
                yield hydrate_partial(query.model, plan, missing, row)
            return
        async for row in self._driver.fetch_iter(sql, params, chunk=chunk):
            # `_instantiate` and not `hydrate`: it is the only place that decides the concrete class of
            # a polymorphic hierarchy, and calling `hydrate` straight made a streamed read answer with
            # the BASE class while `all()` over the same query answered with the children — and left the
            # siblings' columns on the instance. `_instantiate`'s own docstring lists the paths that
            # inherit the dispatch; this one was missing from the list rather than from the design.
            yield _instantiate(query.model, table, row)

    async def all(
        self, query: SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T]
    ) -> list[T]:
        """Runs the query and returns the rows as instances of the model.

        It loads the `include`/`prefetch` relationships with the SAME criteria as the synchronous
        session (to-one by LEFT JOIN, to-many by select-in, one query per level): the plans are shared.
        """
        if isinstance(query, (SnakeCompound, SnakeRecursive)) or not query.has_includes:
            sql, params = query.to_sql(self._dialect)
            table = registry_of(query.model).table_of(query.model)
            assert table is not None
            rows = await self._driver.fetch_all(sql, params)
            return map_rows(query, rows)

        if query.to_one_includes():
            sql, params = query.to_include_sql(self._dialect)
            segments = query.include_segments()
            rows = await self._driver.fetch_all(sql, params)
            parents = cast("list[T]", instantiate_rows_with_includes(segments, rows))
        else:
            sql, params = query.to_sql(self._dialect)
            table = registry_of(query.model).table_of(query.model)
            assert table is not None
            rows = await self._driver.fetch_all(sql, params)
            parents = map_rows(query, rows)

        parent_table = registry_of(query.model).table_of(query.model)
        assert parent_table is not None
        for relationship in query.to_many_includes():
            await self._load_to_many(parents, parent_table, relationship)
        for prefetch in query.prefetches():
            await self._run_prefetch(parents, prefetch)
        return parents

    async def _load_to_many(
        self,
        parents: Sequence[object],
        parent_table: SnakeTableInfo,
        relationship: SnakeRelationshipInfo,
    ) -> None:
        """Loads a ONE-hop to-many relationship with a select-in."""
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
        await self._load_level(parents, hop)

    async def _run_prefetch(
        self, roots: Sequence[object], prefetch: SnakePrefetch[Any]
    ) -> None:
        """Resolves a nested prefetch chain LEVEL BY LEVEL: one query per hop, never an N+1.

        The frontier starts at the roots and advances hop by hop (one level's children are the next
        one's frontier). If it empties out, the chain stops: there are no parents to hang
        grandchildren on.
        """
        frontier: list[object] = list(roots)
        for hop in prefetch.hops():
            if not frontier:
                break
            frontier = await self._load_level(frontier, hop)

    async def _load_level(
        self, parents: Sequence[object], hop: SnakePrefetchHop
    ) -> list[object]:
        """Runs the plan of ONE level (to-one, to-many or many-to-many), in as many statements as the
        engine's placeholder ceiling needs.

        Which plan is due is decided by `planning.plan_level`, and how many parents fit in a batch by
        `planning.parents_per_batch` — the same two the synchronous session uses. Splitting here in a
        way of its own is exactly how the two halves drifted the last time.
        """
        loaded: list[object] = []
        size = parents_per_batch(hop, self._dialect)
        for start in range(0, len(parents), size):
            plan = plan_level(parents[start : start + size], hop, self._dialect)
            if plan is None:
                continue
            sql, params, attach = plan
            loaded.extend(attach(await self._driver.fetch_all(sql, params)))
        return loaded

    async def first(
        self, query: SnakeQuery[T] | SnakeCompound[T] | SnakeRecursive[T]
    ) -> T | None:
        """The first row, or None. It bounds with LIMIT 1: it does not fetch the rest just to throw it away."""
        rows = await self.all(query.limit(1))
        return rows[0] if rows else None

    async def count(self, query: SnakeQuery[T]) -> int:
        """Counts the rows that match the query."""
        guard_plain_query(query, "count")
        sql, params = query.to_count_sql(self._dialect)
        return cast(
            "int",
            await self._run(plan_scalar(sql, params, lambda v: int(cast("int", v)))),
        )

    async def exists(self, query: SnakeQuery[T]) -> bool:
        """Tells whether any row matching the query exists."""
        guard_plain_query(query, "exists")
        sql, params = query.to_exists_sql(self._dialect)
        return cast("bool", await self._run(plan_scalar(sql, params, bool)))

    async def add(self, instance: ModelT) -> ModelT:
        """Inserts the instance and copies back onto it whatever the `RETURNING` gives.

        The plan is built by `planning.plan_insert`, the same one as the synchronous session (a
        single decision about which columns go and what gets copied back).
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
        await self._run(plan)
        if not self._dialect.supports_returning:
            # Same as in the synchronous one: without RETURNING the PK does not come back in the
            # row and it has to be fetched from the driver. It does not fit in the plan because the
            # plan is COLOURLESS and this asks the connection — which is exactly why it was left
            # unwritten here.
            apply_last_insert_id(instance, table, self._driver)
        emit_signal(type(instance), SnakeSignal.POST_SAVE, instance)
        return instance

    async def update(self, instance: SnakeModel) -> None:
        """Updates the instance's non-PK columns, filtering by its primary key."""
        table = table_with_pk(instance)
        values = update_values(instance, table)
        emit_signal(type(instance), SnakeSignal.PRE_SAVE, instance)
        sql, params = emit_update(
            table, self._dialect, values, where=pk_condition(table, instance)
        )
        await self._driver.execute(sql, params)
        emit_signal(type(instance), SnakeSignal.POST_SAVE, instance)

    async def delete(self, instance: SnakeModel) -> None:
        """Deletes the instance's row, filtering by its primary key."""
        table = table_with_pk(instance)
        emit_signal(type(instance), SnakeSignal.PRE_DELETE, instance)
        sql, params = emit_delete(
            table, self._dialect, where=pk_condition(table, instance)
        )
        await self._driver.execute(sql, params)
        emit_signal(type(instance), SnakeSignal.POST_DELETE, instance)

    async def delete_where(self, query: SnakeQuery[ModelT], /) -> int:
        """Deletes IN BULK the rows that match the filter. It warns about the signals it skips."""
        warn_bulk_skips_signals(query.model, "delete_where")
        sql, params = query.to_delete_sql(self._dialect)
        return await self._driver.execute(sql, params)

    async def update_where(
        self, query: SnakeQuery[ModelT], values: list[tuple[Any, object]], /
    ) -> int:
        """Updates IN BULK. It warns about the signals it skips, just like the synchronous session."""
        warn_bulk_skips_signals(query.model, "update_where")
        columns: dict[str, object] = {}
        for column, value in values:
            guard_set_value(value)
            columns[column_name(column)] = value
        # Same guard as the synchronous session: a declared limit holds just the same while
        # awaiting. The EXPRESSIONS, whose value the server computes, are filtered out.
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
        sql, params = query.to_update_sql(self._dialect, columns)
        return await self._driver.execute(sql, params)

    async def select(
        self,
        query: SnakeQuery[Any] | SnakeJoinedQuery[Any, Any],
        /,
        *columns: SnakeValue[Any],
    ) -> list[tuple[Any, ...]]:
        """Projects columns and/or aggregates: it returns TUPLES, not instances.

        The projection and the coercion live in `planning.project_rows`, colourless: here it only
        awaits. Typed like its synchronous sibling's implementation: `query: Any` there switched off
        the guard that a compound query cannot be projected, and `*columns: Any` let a plain value
        through where a `SnakeValue` is required.
        """
        guard_plain_query(query, "select")
        sql, params = query.to_project_sql(self._dialect, columns)
        rows = await self._driver.fetch_all(sql, params)
        return project_rows(query, columns, rows)

    async def annotate(
        self,
        query: SnakeQuery[T],
        result: type[R],
        /,
        **aggregates: SnakeValue[Any],
    ) -> list[R]:
        """Annotates each row with aggregates and wraps it in a typed `@snake_result`.

        Typed EXACTLY like its synchronous sibling: the `R: SnakeResult` bound (which rejects a
        `result` that is not a `@snake_result`) must stay live in async, not `Any -> list[Any]`.
        """
        sql, params, build = plan_annotate(query, result, self._dialect, aggregates)
        return build(await self._driver.fetch_all(sql, params))

    async def call(
        self, name: str, args: Sequence[object], *, into: type[Row]
    ) -> list[Row]:
        """Calls a database FUNCTION that returns rows and hydrates them into `into`.

        Typed EXACTLY like its synchronous sibling: `into: Any -> list[Any]` would switch off the
        `Row: SnakeRow` bound (the lock that rejects an `into` that is not a `@snake_row`).
        """
        sql, params, build = plan_call(name, args, into, self._dialect)
        return build(await self._driver.fetch_all(sql, params))

    async def explain(self, query: SnakeQuery[ModelT]) -> list[str]:
        """The plan for this query, without running it. Same contract as the synchronous session."""
        sql, params = query.to_sql(self._dialect)
        rows = await self._driver.fetch_all(self._dialect.explain_sql(sql), params)
        return [
            " ".join("" if cell is None else str(cell) for cell in row) for row in rows
        ]

    async def raw(
        self, sql: str, params: Sequence[object] = (), *, into: type[Row]
    ) -> list[Row]:
        """The escape hatch: raw SQL hydrated into a DECLARED shape (`@snake_row`).

        Parametrised values; the SHAPE is not checked (the same contract as the synchronous session:
        you declare, I hydrate).
        """
        build = plan_raw(into)
        return build(await self._driver.fetch_all(sql, tuple(params)))

    async def add_all(self, instances: Sequence[ModelT], /) -> None:
        """Inserts a batch with a single multi-row INSERT per chunk.

        The PREs are ALL fired before anything is emitted (a handler can modify the instance, and
        doing so halfway through the batch would leave some rows with the change and others without).
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
        for instance in instances:
            emit_signal(model, SnakeSignal.PRE_SAVE, instance)
        warn_bulk_loses_generated_keys(self._dialect, table)
        rows = [insert_values(instance, table) for instance in instances]
        # The same guard as the synchronous colour, from the same shared function: the defect was
        # identical in both, letting the first instance answer for the batch.
        guard_uniform_bulk_columns(rows, model.__name__)
        # An all-defaults batch -> `insert_values` gives `{}` -> `DEFAULT VALUES`, of ONE row
        # (there is no portable all-defaults multi-row). Same path as `add`.
        if not rows[0]:
            for instance in instances:
                sql, params = emit_insert(table, self._dialect, {})
                if self._dialect.supports_returning:
                    apply_returned(
                        instance, table, (await self._driver.fetch_all(sql, params))[0]
                    )
                else:
                    await self._driver.execute(sql, params)
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
                returned = await self._driver.fetch_all(sql, params)
                for instance, row in zip(batch, returned, strict=True):
                    apply_returned(instance, table, row)
            else:
                await self._driver.execute(sql, params)
        for instance in instances:
            emit_signal(model, SnakeSignal.POST_SAVE, instance)

    async def upsert(
        self,
        instance: SnakeModel,
        /,
        *,
        on_conflict: Sequence[Any],
        update: Sequence[Any] = (),
    ) -> None:
        """Inserts resolving the conflict over `on_conflict` (an idempotent upsert)."""
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
            rows = await self._driver.fetch_all(sql, params)
            if rows:
                apply_returned(instance, table, rows[0])
        else:
            await self._driver.execute(sql, params)
        emit_signal(type(instance), SnakeSignal.POST_SAVE, instance)

    async def refresh(self, instance: ModelT) -> ModelT:
        """Reloads the instance from the database, overwriting ALL of its columns."""
        table = table_with_pk(instance)
        sql, params = emit_select(
            table, self._dialect, where=pk_condition(table, instance)
        )
        rows = await self._driver.fetch_all(sql, params)
        if not rows:
            raise SnakeRegistryError(
                f"{type(instance).__name__} could not be refreshed: its row is gone from "
                f"'{table.name}'. Did another transaction delete it?"
            )
        apply_returned(instance, table, rows[0])
        return instance

    async def get_or_create(
        self, query: SnakeQuery[ModelT], build: Callable[[], ModelT]
    ) -> tuple[ModelT, bool]:
        """Looks it up and, if there is nothing, inserts whatever `build` returns. Gives `(row, created)`.

        The boolean is the reason it exists: `upsert` writes too, but it does not say whether it
        created it or it was already there.
        """
        found = await self.first(query)
        if found is not None:
            return found, False
        return await self.add(build()), True

    async def set_isolation(self, level: SnakeIsolation) -> None:
        """Sets the ISOLATION of the transaction starting now (before reading or writing).

        The engine is ASKED first, through the SAME guard the synchronous session calls. This used
        to hand the statement straight to the driver, so on an engine without it SQLite answered
        `near "SET": syntax error` — the failure its sibling's docstring says the check exists to
        prevent, alive in this colour because the fix had been applied to one of the two.
        """
        guard_can_set_isolation(self._dialect)
        await self._driver.execute(f"SET TRANSACTION ISOLATION LEVEL {level.value}", ())

    @asynccontextmanager
    async def savepoint(self) -> AsyncIterator[None]:
        """SAVEPOINT as an asynchronous context manager: it isolates a block inside the transaction.

        Same contract as the synchronous one (nesting by depth): on a clean exit `RELEASE`, if the
        block raises it discards ONLY what is inside and re-raises.
        """
        self._savepoint_depth += 1
        name = f"sp{self._savepoint_depth}"
        await self._driver.savepoint(name)
        try:
            yield
        except Exception:
            await self._driver.rollback_to_savepoint(name)
            raise
        else:
            await self._driver.release_savepoint(name)
        finally:
            self._savepoint_depth -= 1

    async def execute_procedure(self, name: str, args: Sequence[object]) -> None:
        """Runs a PROCEDURE that returns NO rows (`CALL name(...)`); the opposite of `call(...)`.

        The ARGS travel parametrised (user data); the NAME goes through the same `routine_name`
        check the other three doors use — the SAME sentence, not a reworded one.
        """
        checked = routine_name(name)
        placeholders = ", ".join(
            self._dialect.placeholder(index + 1) for index in range(len(args))
        )
        await self._driver.execute(f"CALL {checked}({placeholders})", list(args))

    async def commit(self) -> None:
        """Commits the transaction in progress."""
        await self._driver.commit()

    async def rollback(self) -> None:
        """Rolls back the transaction in progress."""
        await self._driver.rollback()

    async def close(self) -> None:
        """Closes the underlying connection."""
        await self._driver.close()
